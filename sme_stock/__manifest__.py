# -*- coding: utf-8 -*-
{
    'name': "SMEi Inventory Custom",

    'summary': """
        Validating picking with back date entry""",

    'description': """
       Validating picking with back date entry
    """,

    'author': "SME Intellect Co. Ltd",
    'website': "https://www.smeintellect.com/",
    'category': 'Inventory Management',
    'version': '0.1',

    'depends': ['stock'],

    'data': [

        'views/stock_view.xml',

    ],
    # only loaded in demonstration mode
    # 'demo': [
    #     'demo/demo.xml',
    # ],
}
