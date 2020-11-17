{
    'name': 'SMEi Stock Ledger Reporting Custom',
    'version': '13.0.1.0.0',
    'author': 'SME Intellect Co., Ltd',
    'category': 'Inventory Management',
    'website': '',
    'depends': ['stock','account_reports',],
    'summary': 'Accounting',
    'description': """
     Stock Reporting 
    ====================
    - Stock Ledger Report   
   """,
    # 'demo': [''],
    'data': [
        'security/ir.model.access.csv',
        'data/stock_ledger_report_data.xml',
        'views/report_stock_ledger.xml',
        'views/search_template_view.xml',
        'views/assets.xml'
    ],
    'qweb': [
        'static/src/xml/stock_report_template.xml',
    ],
    'css': [' '],

    'application': True
}