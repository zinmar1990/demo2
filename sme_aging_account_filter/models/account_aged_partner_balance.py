# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.

from odoo import models, api, _, _lt, fields

class report_account_aged_partner(models.AbstractModel):
    _inherit = "account.aged.partner"

    filter_accounts = True

    @api.model
    def _get_filter_accounts(self):
        domain =[]
        if self.env.context.get('model') == 'account.aged.receivable':
            domain.append('receivable')
        else:
            domain.append('payable')

        return self.env['account.account'].search([
            ('internal_type','in',domain),
            ('company_id', 'in', self.env.user.company_ids.ids or [self.env.company.id])
        ], order="company_id, name")

    @api.model
    def _get_filter_account_groups(self):
        accounts = self._get_filter_accounts()
        groups = self.env['account.group'].search([], order='code_prefix')
        ret = self.env['account.group']
        for account_group in groups:
            # Only display the group if it doesn't exclude every account
            if accounts - account_group.excluded_account_ids:
                ret += account_group
        return ret

    @api.model
    def _init_filter_accounts(self, options, previous_options=None):
        if self.filter_accounts is None:
            return

        previous_company = False
        if previous_options and previous_options.get('accounts'):
            account_map = dict((opt['id'], opt['selected']) for opt in previous_options['accounts'] if
                               opt['id'] != 'divider' and 'selected' in opt)
        else:
            account_map = {}
        options['accounts'] = []

        group_header_displayed = False
        default_group_ids = []
        for group in self._get_filter_account_groups():
            account_ids = (self._get_filter_accounts() - group.excluded_account_ids).ids
            if len(account_ids):
                if not group_header_displayed:
                    group_header_displayed = True
                    options['accounts'].append({'id': 'divider', 'name': _('Journal Groups')})
                    default_group_ids = account_ids
                options['accounts'].append({'id': 'group', 'name': group.name, 'ids': account_ids})

        for a in self._get_filter_accounts():
            if a.company_id != previous_company:
                options['accounts'].append({'id': 'divider', 'name': a.company_id.name})
                previous_company = a.company_id
            options['accounts'].append({
                'id': a.id,
                'name': a.name,
                'code': a.code,
                'type': a.internal_type,
                'selected': account_map.get(a.id, a.id in default_group_ids),
            })

    @api.model
    def _get_options_accounts(self, options):
        return [
            account for account in options.get('accounts', []) if
            not account['id'] in ('divider', 'group') and account['selected']
        ]

    @api.model
    def _get_options_accounts_domain(self, options):
        # Make sure to return an empty array when nothing selected to handle archived journals.
        selected_accounts = self._get_options_accounts(options)
        return selected_accounts and [('journal_id', 'in', [j['id'] for j in selected_accounts])] or []

    def _set_context(self, options):
        ctx = super(report_account_aged_partner, self)._set_context(options)
        if options.get('accounts'):
            ctx['account_ids'] = [j.get('id') for j in options.get('accounts') if j.get('selected')]

        return ctx

    def _get_templates(self):
        return {
                'main_template': 'account_reports.main_template',
                'main_table_header_template': 'account_reports.main_table_header',
                'line_template': 'account_reports.line_template',
                'footnotes_template': 'account_reports.footnotes_template',
                'search_template': 'sme_aging_account_filter.search_template_aging',
        }

    def get_report_informations(self, options):

        options = self._get_options(options)
        info = super(report_account_aged_partner, self).get_report_informations(options)
        if options.get('accounts'):
            accounts_selected = set(account['id'] for account in options['accounts'] if account.get('selected'))
            for account_group in self.env['account.group'].search([]):
                if accounts_selected and accounts_selected == set(self._get_filter_accounts().ids) - set(account_group.excluded_account_ids.ids):
                    options['name_account_group'] = account_group.name
                    break

        report_manager = self._get_report_manager(options)
        searchview_dict = {'options': options, 'context': self.env.context}
        info = {'options': options,
                'context': self.env.context,
                'report_manager_id': report_manager.id,
                'footnotes': [{'id': f.id, 'line': f.line, 'text': f.text} for f in report_manager.footnotes_ids],
                'buttons': self._get_reports_buttons_in_sequence(),
                'main_html': self.get_html(options),
                'searchview_html': self.env['ir.ui.view'].render_template(
                    self._get_templates().get('search_template', 'sme_aging_account_filter.search_template_aging'),
                    values=searchview_dict),
                }
        return info

class report_account_aged_receivable(models.AbstractModel):
    _inherit = "account.aged.receivable"


class report_account_aged_payable(models.AbstractModel):
    _inherit = "account.aged.payable"


