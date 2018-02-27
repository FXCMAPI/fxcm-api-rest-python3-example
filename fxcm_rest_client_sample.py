import json
import fxcm_rest_api_token as fxcm_rest_api
import time

trader = fxcm_rest_api.Trader('YOURTOKEN', 'demo') # demo for demo 
trader.login()
try:
    print("Logged in, now getting Account details")
    while len(trader.account_list) < 1:
           time.sleep(0.1)
    account_id = trader.account_list[0]
    print(trader.account_id == account_id)
    print("Opening a trade now -USD/JPY 10 lots on %s" % account_id)
    response = trader.open_trade(account_id, "USD/JPY", True, 10)
    print(response)
    if response['status'] is True:
        orderId = response['data']['orderId']
        tradeId = trader.get_tradeId(orderId)
        print("TradeID: ", tradeId)
        print("Open trade response: ", response)
        positions = trader.get_model("OpenPosition")        
        print("Positions: ", positions)
        response = trader.close_all_for_symbol("USD/JPY")
        print("Close All result:\n\n", response['status'], response, "\n\n")
        positions = trader.get_model("OpenPosition")
        print("Positions: ", positions)

        c = trader.candles("EUR/USD", "m15", 15, dt_fmt="%Y/%m/%d %H:%M:%S")['candles']
        print(len(c))
        for candle in c:
            print(candle)        

        
        c = trader.get_candles("USD/JPY", "M1", 10)
        for candle in c['candles']:
            print(candle)
except Exception as e:
    print(str(e))


