# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.

from odoo import models, api, _, _lt, fields
from odoo.tools.misc import format_date
from datetime import timedelta


class ReportStockLedger(models.AbstractModel):
    _inherit = "stock.custom.report"
    _name = "stock.ledger"
    _description = "Stock Ledger"

    filter_date = {'mode': 'range', 'filter': 'this_year'}
    filter_all_entries = False
    filter_unfold_all = False
    filter_partner = False


    @api.model
    def _get_templates(self):
        templates = super(ReportStockLedger, self)._get_templates()
        templates['main_template'] = 'sme_stock_ledger.template_stock_ledger_report'
        templates['line_template'] = 'sme_stock_ledger.line_template_stock_ledger_report'
        templates['search_template'] = 'sme_stock_ledger.search_template'
        return templates

    ####################################################
    # OPTIONS
    ####################################################




    @api.model
    def _get_options_sum_balance(self, options):
        ''' Create options with the 'strict_range' enabled on the filter_date.
        The resulting dates domain will be:
        [
            ('date' <= options['date_to']),
            ('date' >= options['date_from'])
        ]
        :param options: The report options.
        :return:        A copy of the options.
        '''
        new_options = options.copy()
        new_options['date'] = new_options['date'].copy()
        new_options['date']['strict_range'] = True
        return new_options

    @api.model
    def _get_options_initial_balance(self, options):
        ''' Create options used to compute the initial balances for each partner.
        The resulting dates domain will be:
        [('date' <= options['date_from'] - 1)]
        :param options: The report options.
        :return:        A copy of the options.
        '''
        new_options = options.copy()
        new_options['date'] = new_options['date'].copy()
        new_date_to = fields.Date.from_string(new_options['date']['date_from']) - timedelta(days=1)
        new_options['date'].update({
            'date_from': False,
            'date_to': fields.Date.to_string(new_date_to),
        })
        return new_options

    ####################################################
    # QUERIES
    ####################################################
    @api.model
    def _get_query_sums_transfer(self, options,locations, expanded_product=None):
        params = []
        queries = []

        if expanded_product:
            domain = [('product_id', '=', expanded_product.id)]
        else:
            domain = []
        new_options = self._get_options_sum_balance(options)
        tables, where_clause, where_params = self._query_get(new_options, domain=domain)
        params += where_params
        where_clause += ' AND stock_move_line.location_id IN %s '
        params += locations
        queries.append('''
           SELECT
               stock_move_line.product_id  AS product_id,
               0.0 as debit,
               stock_move_line.qty_done    AS credit
           FROM %s
           LEFT JOIN stock_move ON stock_move.id = stock_move_line.move_id
           LEFT JOIN stock_valuation_layer ON stock_valuation_layer.stock_move_id = stock_move.id
           LEFT JOIN stock_location source_location           ON source_location.id = stock_move_line.location_id
           LEFT JOIN stock_location dest_location           ON dest_location.id = stock_move_line.location_dest_id
           WHERE source_location.usage = 'internal' AND dest_location.usage = 'internal' AND %s
               ''' % (tables, where_clause))

        # sum internal transfer In
        tables, where_clause, where_params = self._query_get(new_options, domain=domain)
        params += where_params
        where_clause += ' AND stock_move_line.location_dest_id IN %s '
        params += locations
        queries.append('''
            SELECT
               stock_move_line.product_id AS product_id,       
               stock_move_line.qty_done AS debit,
               0.0 as credit                     
           FROM %s
           LEFT JOIN stock_move ON stock_move.id = stock_move_line.move_id
           LEFT JOIN stock_valuation_layer ON stock_valuation_layer.stock_move_id = stock_move.id
           LEFT JOIN stock_location source_location  ON source_location.id = stock_move_line.location_id
           LEFT JOIN stock_location dest_location  ON dest_location.id = stock_move_line.location_dest_id
           WHERE source_location.usage = 'internal' AND dest_location.usage = 'internal' AND %s
               ''' % (tables, where_clause))

        query = '''
            SELECT A.product_id as groupby,
            \'sum\' as key,
             sum(A.debit) as debit,
             sum(A.credit) as credit,
             sum(A.debit - A.credit) as balance 
             FROM ( ''' + ' UNION ALL '.join(queries) + ''' )A 
             GROUP BY A.product_id '''

        return query,params

    @api.model
    def _get_query_sums(self, options, expanded_product=None):
        ''' Construct a query retrieving all the aggregated sums to build the report. It includes:
        - sums for all accounts.
        - sums for the initial balances.
        - sums for the unaffected earnings.
        - sums for the tax declaration.
        :param options:             The report options.
        :param expanded_partner:    An optional account.account record that must be specified when expanding a line
                                    with of without the load more.
        :return:                    (query, params)
        '''
        params = []
        queries = []

        if expanded_product:
            domain = [('product_id', '=', expanded_product.id)]
        else:
            domain = []

        # Create the currency table.


        # Get sums for all stocks.
        # period: [('date' <= options['date_to']), ('date' >= options['date_from'])]
        new_options = self._get_options_sum_balance(options)
        tables, where_clause, where_params = self._query_get(new_options, domain=domain)
        params += where_params
        if options.get('locations'):
            locations = [l.get('id') for l in options.get('locations') if l.get('selected')]
            if locations:
                where_clause += ' AND (stock_move_line.location_id IN %s OR stock_move_line.location_dest_id IN %s)'
                params += (tuple(locations or [0]),tuple(locations or [0]),)

        queries.append('''
            SELECT
                stock_move_line.product_id        AS groupby,
                'sum'                               AS key,
                SUM(ROUND(CASE WHEN stock_valuation_layer.quantity >= 0 THEN stock_valuation_layer.quantity ELSE 0 END ))   AS debit,
                SUM(ROUND(CASE WHEN stock_valuation_layer.quantity <= 0 THEN (0-stock_valuation_layer.quantity) ELSE 0 END  ))  AS credit,
                SUM(ROUND(stock_valuation_layer.quantity)) AS balance
            FROM %s
            LEFT JOIN stock_move ON stock_move.id = stock_move_line.move_id
            LEFT JOIN stock_valuation_layer ON stock_valuation_layer.stock_move_id = stock_move.id
            WHERE %s
            GROUP BY stock_move_line.product_id
        ''' % (tables,  where_clause))

        # Get sums for the initial balance.
        # period: [('date' <= options['date_from'] - 1)]
        new_options = self._get_options_initial_balance(options)
        tables, where_clause, where_params = self._query_get(new_options, domain=domain)
        params += where_params
        queries.append('''
            SELECT
                stock_move_line.product_id        AS groupby,
                'initial_balance'                   AS key,
                SUM(ROUND(CASE WHEN stock_valuation_layer.quantity >= 0 THEN stock_valuation_layer.quantity ELSE 0 END ))   AS debit,
                SUM(ROUND(CASE WHEN stock_valuation_layer.quantity <= 0 THEN (0-stock_valuation_layer.quantity) ELSE 0 END  ))  AS credit,
                SUM(ROUND(stock_valuation_layer.quantity)) AS balance
            FROM %s
            LEFT JOIN stock_move ON stock_move.id = stock_move_line.move_id
            INNER JOIN stock_valuation_layer ON stock_valuation_layer.stock_move_id = stock_move.id
            WHERE %s
            GROUP BY stock_move_line.product_id
        ''' % (tables, where_clause))
        if options.get('locations'):
            locations = [l.get('id') for l in options.get('locations') if l.get('selected')]
            if locations:
                # sum internal transfer out
                tables, where_clause, where_params = self._query_get(new_options, domain=domain)
                params += where_params
                where_clause += ' AND ( stock_move_line.location_id IN %s )'
                params += (tuple(locations or [0]),)
                queries.append('''
                   SELECT
                       stock_move_line.product_id        AS groupby,
                       'initial_balance'                 AS key,
                       0.0 as debit,
                       sum(0-stock_move_line.qty_done )   AS credit,
                       sum(0-stock_move_line.qty_done )   AS balance
                   FROM %s
                   LEFT JOIN stock_move ON stock_move.id = stock_move_line.move_id
                   LEFT JOIN stock_valuation_layer ON stock_valuation_layer.stock_move_id = stock_move.id
                   LEFT JOIN stock_location source_location           ON source_location.id = stock_move_line.location_id
                   LEFT JOIN stock_location dest_location           ON dest_location.id = stock_move_line.location_dest_id
                   WHERE source_location.usage = 'internal' AND dest_location.usage = 'internal' AND %s
                   GROUP BY stock_move_line.product_id
                       ''' % (tables, where_clause))

                # sum internal transfer In
                tables, where_clause, where_params = self._query_get(new_options, domain=domain)
                params += where_params
                where_clause += ' AND ( stock_move_line.location_dest_id IN %s )'
                params += (tuple(locations or [0]),)
                queries.append('''
                   SELECT
                       stock_move_line.product_id        AS groupby,
                       'initial_balance'                AS key,
                       sum(stock_move_line.qty_done )   AS debit,
                       0.0 as credit,
                       sum(stock_move_line.qty_done )   AS balance
                   FROM %s
                   LEFT JOIN stock_move ON stock_move.id = stock_move_line.move_id
                   LEFT JOIN stock_valuation_layer ON stock_valuation_layer.stock_move_id = stock_move.id
                   LEFT JOIN stock_location source_location           ON source_location.id = stock_move_line.location_id
                   LEFT JOIN stock_location dest_location           ON dest_location.id = stock_move_line.location_dest_id
                   WHERE source_location.usage = 'internal' AND dest_location.usage = 'internal' AND %s
                  GROUP BY stock_move_line.product_id
                       ''' % (tables, where_clause))


        return ' UNION ALL '.join(queries), params

    @api.model
    def _get_query_smls(self, options, expanded_product=None, offset=None, limit=None):
        ''' Construct a query retrieving the account.move.lines when expanding a report line with or without the load
        more.
        :param options:             The report options.
        :param expanded_partner:    The res.partner record corresponding to the expanded line.
        :param offset:              The offset of the query (used by the load more).
        :param limit:               The limit of the query (used by the load more).
        :return:                    (query, params)
        '''
        unfold_all = options.get('unfold_all') or (self._context.get('print_mode') and not options['unfolded_lines'])
        params = []
        queries = []
        # Get sums for the account move lines.
        # period: [('date' <= options['date_to']), ('date', '>=', options['date_from'])]
        if expanded_product:
            domain = [('product_id', '=', expanded_product.id)]
        elif unfold_all:
            domain = []
        elif options['unfolded_lines']:
            domain = [('product_id', 'in', [int(line[8:]) for line in options['unfolded_lines']])]

        new_options = self._get_options_sum_balance(options)
        tables, where_clause, where_params = self._query_get(new_options, domain=domain)
        params += where_params
        if options.get('locations'):
            locations = [l.get('id') for l in options.get('locations') if l.get('selected')]
            if locations:
                where_clause += ' AND (stock_move_line.location_id IN %s OR stock_move_line.location_dest_id IN %s)'
                params += (tuple(locations or [0]),tuple(locations or [0]),)

        queries.append('''
            SELECT
                stock_move_line.id,
                stock_move_line.date,
                stock_move.origin,
                stock_move.date_expected,
                uom.name as uom_name,
                stock_move_line.reference,
                stock_move_line.company_id,
                stock_move_line.location_id,             
                stock_move_line.location_dest_id,
                stock_move_line.product_id,
                stock_move.partner_id,
                ROUND(CASE WHEN layer.quantity >= 0 THEN layer.quantity ELSE 0 END )  AS debit,
                ROUND(CASE WHEN layer.quantity <= 0 THEN (0-layer.quantity) ELSE 0 END )  AS credit,
                ROUND(layer.quantity) AS balance,
                stock_move_line__move_id.name           AS move_name,                
                partner.name                            AS partner_name,              
                source_location.complete_name           AS source_name,
                dest_location.complete_name             AS dest_name
            FROM %s
            LEFT JOIN stock_move stock_move_line__move_id ON stock_move_line__move_id.id = stock_move_line.move_id           
            LEFT JOIN res_company company               ON company.id = stock_move_line.company_id           
            LEFT JOIN uom_uom uom               ON uom.id = stock_move_line.product_uom_id
            LEFT JOIN stock_location source_location           ON source_location.id = stock_move_line.location_id
            LEFT JOIN stock_location dest_location           ON dest_location.id = stock_move_line.location_dest_id
            LEFT JOIN stock_move ON stock_move.id = stock_move_line.move_id              
            INNER JOIN stock_valuation_layer layer           ON layer.stock_move_id = stock_move.id 
            LEFT JOIN stock_picking picking           ON picking.id = stock_move.picking_id
            LEFT JOIN res_partner partner               ON partner.id = picking.partner_id                
            WHERE %s          
        ''' % (tables,where_clause))

        # internal transfer in and out by location
        if options.get('locations'):
            locations = [l.get('id') for l in options.get('locations') if l.get('selected')]
            if locations:
                tables, where_clause, where_params = self._query_get(new_options, domain=domain)
                params += where_params
                where_clause += ' AND ( stock_move_line.location_dest_id IN %s )'
                params += (tuple(locations or [0]),)
                queries.append('''
                      SELECT
                         stock_move_line.id,
                         stock_move_line.date,
                         stock_move.origin,
                         stock_move.date_expected,
                         uom.name as uom_name,
                         stock_move_line.reference,
                         stock_move_line.company_id,
                         stock_move_line.location_id,
                         stock_move_line.location_dest_id,
                         stock_move_line.product_id,
                         stock_move.partner_id,
                         stock_move_line.qty_done AS debit,
                         0.0 AS credit,
                         stock_move_line.qty_done AS balance,
                         stock_move_line__move_id.name           AS move_name,
                         partner.name                            AS partner_name,
                         source_location.complete_name           AS source_name,
                         dest_location.complete_name             AS dest_name
                     FROM %s
                     LEFT JOIN stock_move stock_move_line__move_id ON stock_move_line__move_id.id = stock_move_line.move_id
                     LEFT JOIN res_company company               ON company.id = stock_move_line.company_id
                     LEFT JOIN uom_uom uom               ON uom.id = stock_move_line.product_uom_id
                     LEFT JOIN stock_location source_location           ON source_location.id = stock_move_line.location_id
                     LEFT JOIN stock_location dest_location           ON dest_location.id = stock_move_line.location_dest_id
                     LEFT JOIN stock_move ON stock_move.id = stock_move_line.move_id
                     LEFT JOIN stock_picking picking           ON picking.id = stock_move.picking_id
                     LEFT JOIN res_partner partner               ON partner.id = picking.partner_id
                     WHERE source_location.usage = 'internal' AND dest_location.usage = 'internal' AND %s
                         ''' % (tables, where_clause))

                tables, where_clause, where_params = self._query_get(new_options, domain=domain)
                params += where_params
                where_clause += ' AND ( stock_move_line.location_id IN %s )'
                params += (tuple(locations or [0]),)
                queries.append('''
                    SELECT
                       stock_move_line.id,
                       stock_move_line.date,
                       stock_move.origin,
                       stock_move.date_expected,
                       uom.name as uom_name,
                       stock_move_line.reference,
                       stock_move_line.company_id,
                       stock_move_line.location_id,             
                       stock_move_line.location_dest_id,
                       stock_move_line.product_id,
                       stock_move.partner_id,
                       0.0 AS debit,
                       stock_move_line.qty_done AS credit,
                       0-stock_move_line.qty_done AS balance,
                       stock_move_line__move_id.name           AS move_name,                
                       partner.name                            AS partner_name,              
                       source_location.complete_name           AS source_name,
                       dest_location.complete_name             AS dest_name
                   FROM %s
                   LEFT JOIN stock_move stock_move_line__move_id ON stock_move_line__move_id.id = stock_move_line.move_id           
                   LEFT JOIN res_company company               ON company.id = stock_move_line.company_id           
                   LEFT JOIN uom_uom uom               ON uom.id = stock_move_line.product_uom_id
                   LEFT JOIN stock_location source_location           ON source_location.id = stock_move_line.location_id
                   LEFT JOIN stock_location dest_location           ON dest_location.id = stock_move_line.location_dest_id
                   LEFT JOIN stock_move ON stock_move.id = stock_move_line.move_id    
                   LEFT JOIN stock_picking picking           ON picking.id = stock_move.picking_id
                   LEFT JOIN res_partner partner               ON partner.id = picking.partner_id                 
                           WHERE source_location.usage = 'internal' AND dest_location.usage = 'internal' AND %s                        
                               ''' % (tables,where_clause))

            else:
                tables, where_clause, where_params = self._query_get(new_options, domain=domain)
                params += where_params
                queries.append('''
                    SELECT
                       stock_move_line.id,
                       stock_move_line.date,
                       stock_move.origin,
                       stock_move.date_expected,
                       uom.name as uom_name,
                       stock_move_line.reference,
                       stock_move_line.company_id,
                       stock_move_line.location_id,
                       stock_move_line.location_dest_id,
                       stock_move_line.product_id,
                       stock_move.partner_id,
                       stock_move_line.qty_done AS debit,
                       stock_move_line.qty_done AS credit,
                       0.0 AS balance,
                       stock_move_line__move_id.name           AS move_name,
                       partner.name                            AS partner_name,
                       source_location.complete_name           AS source_name,
                       dest_location.complete_name             AS dest_name
                   FROM %s
                   LEFT JOIN stock_move stock_move_line__move_id ON stock_move_line__move_id.id = stock_move_line.move_id
                   LEFT JOIN res_company company               ON company.id = stock_move_line.company_id
                   LEFT JOIN uom_uom uom               ON uom.id = stock_move_line.product_uom_id
                   LEFT JOIN stock_location source_location           ON source_location.id = stock_move_line.location_id
                   LEFT JOIN stock_location dest_location           ON dest_location.id = stock_move_line.location_dest_id
                   LEFT JOIN stock_move ON stock_move.id = stock_move_line.move_id
                   LEFT JOIN stock_picking picking           ON picking.id = stock_move.picking_id
                   LEFT JOIN res_partner partner               ON partner.id = picking.partner_id
                   WHERE source_location.usage = 'internal' AND dest_location.usage = 'internal' AND %s
                       ''' % (tables, where_clause))
        return ' UNION ALL '.join(queries), params

    @api.model
    def _do_query(self, options, expanded_product=None):
        ''' Execute the queries, perform all the computation and return partners_results,
        a lists of tuple (partner, fetched_values) sorted by the table's model _order:
            - partner is a res.parter record.
            - fetched_values is a dictionary containing:
                - sum:                              {'debit': float, 'credit': float, 'balance': float}
                - (optional) initial_balance:       {'debit': float, 'credit': float, 'balance': float}
                - (optional) lines:                 [line_vals_1, line_vals_2, ...]
        :param options:             The report options.
        :param expanded_account:    An optional account.account record that must be specified when expanding a line
                                    with of without the load more.
        :param fetch_lines:         A flag to fetch the account.move.lines or not (the 'lines' key in accounts_values).
        :return:                    (accounts_values, taxes_results)
        '''
        company_currency = self.env.company.currency_id

        # Execute the queries and dispatch the results.
        query, params = self._get_query_sums(options, expanded_product=expanded_product)
        groupby_products = {}
        self._cr.execute(query, params)
        sums = self._cr.dictfetchall()

        if options.get('locations'):
            locations = [l.get('id') for l in options.get('locations') if l.get('selected')]
            if locations:
                locations = (tuple(locations or [0]),)
                query, params = self._get_query_sums_transfer(options,locations, expanded_product=expanded_product)
                self._cr.execute(query, params)
                sums += self._cr.dictfetchall()

        for res in sums:
            key = res['key']
            if key == 'sum':
                if not company_currency.is_zero(res['debit']) or not company_currency.is_zero(res['credit']):
                    groupby_products.setdefault(res['groupby'], {})
                    groupby_products[res['groupby']][key] = res
            elif key == 'initial_balance':
                if not company_currency.is_zero(res['balance']):
                    groupby_products.setdefault(res['groupby'], {})
                    groupby_products[res['groupby']][key] = res

        # Fetch the lines of unfolded accounts.
        unfold_all = options.get('unfold_all') or (self._context.get('print_mode') and not options['unfolded_lines'])
        if expanded_product or unfold_all or options['unfolded_lines']:
            query, params = self._get_query_smls(options, expanded_product=expanded_product)
            self._cr.execute(query, params)
            for res in self._cr.dictfetchall():
                if res['product_id'] not in groupby_products:
                    continue
                groupby_products[res['product_id']].setdefault('lines', [])
                groupby_products[res['product_id']]['lines'].append(res)

        # Retrieve the partners to browse.
        # groupby_partners.keys() contains all account ids affected by:
        # - the smls in the current period.
        # - the smls affecting the initial balance.
        # Note a search is done instead of a browse to preserve the table ordering.
        if expanded_product:
            products = expanded_product
        elif groupby_products:
            products = self.env['product.product'].with_context(active_test=False).search([('id', 'in', list(groupby_products.keys()))])
        else:
            products = []
        return [(product, groupby_products[product.id]) for product in products]

    ####################################################
    # COLUMNS/LINES
    ####################################################

    @api.model
    def _get_report_line_product(self, options, product, initial_balance, debit, credit, balance):
        company_currency = self.env.company.currency_id
        unfold_all = self._context.get('print_mode') and not options.get('unfolded_lines')
        columns = [
            {'name': self.format_value(initial_balance), 'class': 'number'},
            {'name': self.format_value(debit), 'class': 'number'},
            {'name': self.format_value(credit), 'class': 'number'},
        ]
        if self.user_has_groups('base.group_multi_currency'):
            columns.append({'name': ''})
        columns.append({'name': self.format_value(balance), 'class': 'number'})

        return {
            'id': 'product_%s' % product.id,
            'name': (product.name or '')[:128],
            'columns': columns,
            'level': 2,
            'trust': 'normal',
            'unfoldable': not company_currency.is_zero(debit) or not company_currency.is_zero(credit),
            'unfolded': 'product_%s' % product.id in options['unfolded_lines'] or unfold_all,
            'colspan': 8,
        }

    @api.model
    def _get_report_line_move_line(self, options, product, sml, cumulated_init_balance, cumulated_balance):
        caret_type = 'stock.move'

        columns = [
            {'name': sml['partner_name']},
            {'name': self._format_sml_name(sml['move_name'], sml['reference'])},
            {'name': sml['origin']},
            {'name': sml['source_name']},
            {'name': sml['dest_name']},
            {'name': sml['uom_name']},
            {'name': sml['date_expected']},
            {'name': self.format_value(cumulated_init_balance), 'class': 'number'},
            {'name': self.format_value(sml['debit'], blank_if_zero=True), 'class': 'number'},
            {'name': self.format_value(sml['credit'], blank_if_zero=True), 'class': 'number'},
        ]

        columns.append({'name': self.format_value(cumulated_balance), 'class': 'number'})
        return {
            'id': sml['id'],
            'parent_id': 'product_%s' % product.id,
            'name': format_date(self.env, sml['date']),
            'class': 'date',
            'columns': columns,
            'caret_options': caret_type,
            'level': 4,
        }

    @api.model
    def _get_report_line_load_more(self, options, product, offset, remaining, progress):
        return {
            'id': 'loadmore_%s' % product.id,
            'offset': offset,
            'progress': progress,
            'remaining': remaining,
            'class': 'o_account_reports_load_more text-center',
            'parent_id': 'account_%s' % product.id,
            'name': _('Load more... (%s remaining)' % remaining),
            'colspan': 10,
            'columns': [{}],
        }

    @api.model
    def _get_report_line_total(self, options, initial_balance, debit, credit, balance):
        columns = [
            {'name': self.format_value(initial_balance), 'class': 'number'},
            {'name': self.format_value(debit), 'class': 'number'},
            {'name': self.format_value(credit), 'class': 'number'},
        ]
        if self.user_has_groups('base.group_multi_currency'):
            columns.append({'name': ''})
        columns.append({'name': self.format_value(balance), 'class': 'number'})
        return {
            'id': 'stock_ledger_total_%s' % self.env.company.id,
            'name': _('Total'),
            'class': 'total',
            'level': 1,
            'columns': columns,
            'colspan': 8,
        }

    @api.model
    def _get_stock_ledger_lines(self, options, line_id=None):
        ''' Get lines for the whole report or for a specific line.
        :param options: The report options.
        :return:        A list of lines, each one represented by a dictionary.
        '''
        lines = []
        unfold_all = options.get('unfold_all') or (self._context.get('print_mode') and not options['unfolded_lines'])

        expanded_product= line_id and self.env['product.product'].browse(int(line_id[8:]))
        products_results = self._do_query(options, expanded_product=expanded_product)

        total_initial_balance = total_debit = total_credit = total_balance = 0.0
        for product, results in products_results:
            is_unfolded = 'product_%s' % product.id in options['unfolded_lines']

            # res.partner record line.
            product_sum = results.get('sum', {})
            product_init_bal = results.get('initial_balance', {})

            initial_balance = product_init_bal.get('balance', 0.0)
            debit = product_sum.get('debit', 0.0)
            credit = product_sum.get('credit', 0.0)
            balance = initial_balance + product_sum.get('balance', 0.0)

            lines.append(self._get_report_line_product(options, product, initial_balance, debit, credit, balance))

            total_initial_balance += initial_balance
            total_debit += debit
            total_credit += credit
            total_balance += balance

            if unfold_all or is_unfolded:
                cumulated_balance = initial_balance

                # account.move.line record lines.
                smls = results.get('lines', [])

                load_more_remaining = len(smls)
                load_more_counter = self._context.get('print_mode') and load_more_remaining or self.MAX_LINES

                for sml in smls:
                    # Don't show more line than load_more_counter.
                    if load_more_counter == 0:
                        break

                    cumulated_init_balance = cumulated_balance
                    cumulated_balance += sml['balance']
                    lines.append(self._get_report_line_move_line(options, product, sml, cumulated_init_balance, cumulated_balance))

                    load_more_remaining -= 1
                    load_more_counter -= 1

                if load_more_remaining > 0:
                    # Load more line.
                    lines.append(self._get_report_line_load_more(
                        options,
                        product,
                        self.MAX_LINES,
                        load_more_remaining,
                        cumulated_balance,
                    ))

        if not line_id:
            # Report total line.
            lines.append(self._get_report_line_total(
                options,
                total_initial_balance,
                total_debit,
                total_credit,
                total_balance
            ))
        return lines

    @api.model
    def _load_more_lines(self, options, line_id, offset, load_more_remaining, progress):
        ''' Get lines for an expanded line using the load more.
        :param options: The report options.
        :return:        A list of lines, each one represented by a dictionary.
        '''
        lines = []

        expanded_product = line_id and self.env['product.product'].browse(int(line_id[9:]))

        load_more_counter = self.MAX_LINES

        # Fetch the next batch of lines.
        smls_query, smls_params = self._get_query_smls(options, expanded_product=expanded_product, offset=offset, limit=load_more_counter)
        self._cr.execute(smls_query, smls_params)
        for sml in self._cr.dictfetchall():
            # Don't show more line than load_more_counter.
            if load_more_counter == 0:
                break

            cumulated_init_balance = progress
            progress += sml['balance']

            # account.move.line record line.
            lines.append(self._get_report_line_move_line(options, expanded_product, sml, cumulated_init_balance, progress))

            offset += 1
            load_more_remaining -= 1
            load_more_counter -= 1

        if load_more_remaining > 0:
            # Load more line.
            lines.append(self._get_report_line_load_more(
                options,
                expanded_product,
                offset,
                load_more_remaining,
                progress,
            ))
        return lines

    def _get_columns_name(self, options):
        columns = [
            {},
            {'name': _('Partner')},
            {'name': _('Ref')},
            {'name': _('Origin')},
            {'name': _('Source')},
            {'name': _('Destination')},
            {'name': _('UOM')},
            {'name': _('Date Expected'), 'class': 'date'},
            {'name': _('Initial Balance'), 'class': 'number'},
            {'name': _('Debit'), 'class': 'number'},
            {'name': _('Credit'), 'class': 'number'}]

        columns.append({'name': _('Balance'), 'class': 'number'})

        return columns

    @api.model
    def _get_lines(self, options, line_id=None):
        offset = int(options.get('lines_offset', 0))
        remaining = int(options.get('lines_remaining', 0))
        balance_progress = float(options.get('lines_progress', 0))

        if offset > 0:
            # Case a line is expanded using the load more.
            return self._load_more_lines(options, line_id, offset, remaining, balance_progress)
        else:
            # Case the whole report is loaded or a line is expanded for the first time.
            return self._get_stock_ledger_lines(options, line_id=line_id)

    @api.model
    def _get_report_name(self):
        return _('Stock Ledger')
