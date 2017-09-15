import fxcm_rest_api

trader = fxcm_rest_api.Trader('username', 'password', 'environment')
trader.login()
try:
    print("Logged in, now getting Account details")
    account_id = trader.account_list[0]
    print("Opening a trade now -USD/JPY 10 lots on %s" % account_id)
    response = trader.open_trade(account_id, "USD/JPY", True, 10)
    if response['_status'] is True:
        print("Open trade response: ", response)
        positions = trader.get_model("OpenPosition")
        print("Positions: ", positions)
        response = trader.close_all_for_symbol(account_id, True, "USD/JPY",
                                               "AtMarket", "GTC")
        print("Close All result:\n\n", response['_status'], response, "\n\n")
        positions = trader.get_model("OpenPosition")
        print("Positions: ", positions)

except Exception as e:
    print str(e)

candles = trader.get_candles("USD/JPY", "M1", 10)

