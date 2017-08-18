import fxcm_rest_api
import json
import time

trader = fxcm_rest_api.Trader('user', 'password', 'prod')
trader.login()

status, response = trader.get_model("Account")
accounts = json.loads(response)
try:
    account_id = accounts['accounts'][0]['accountID']
    status, response = trader.open_trade(account_id, "USD/JPY", True, 10)
    if status is True:
        time.sleep(10)
        status, response = trader.get_model("OpenPosition")
        positions = json.loads(response)
        trader.close_all_for_symbol(account_id, True, "USD/JPY", "AtMarket", "GTC")

except Exception as e:
    print str(e)

