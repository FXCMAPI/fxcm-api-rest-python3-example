import fxcm_rest_api
import json
import time

trader = fxcm_rest_api.Trader('user', 'password', 'prod')
trader.login()

status, response = trader.get_model("Account")
accounts = json.loads(response)
''' based on sample results:
{"response":{"executed":true},"accounts":[{"t":6,"ratePrecision":0,"accountId":"1027808","balance":39288.31,"usdMr":0,
"mc":"N","accountName":"01027808","usdMr3":0,"hedging":"N","usableMargin3":39288.31,"usableMarginPerc":100,
"usableMargin3Perc":100,"equity":39288.31,"usableMargin":39288.31,"dayPL":0,"grossPL":0}]}
'''
try:
    account_id = accounts['accounts'][0]['accountID']
    status, response = trader.open_trade(account_id, "USD/JPY", True, 10)
    if status is True:
        time.sleep(10)
        status, response = trader.get_model("OpenPosition")
        positions = json.loads(response)
        # Based on structure returned, find USD/JPY open position and get trade_id. then close or...
        trader.close_all_for_symbol(account_id, True, "USD/JPY", "AtMarket", "GTC")

except Exception as e:
    print str(e)

