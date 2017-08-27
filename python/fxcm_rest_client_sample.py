import fxcm_rest_api

trader = fxcm_rest_api.Trader('username', 'password', 'environment')
trader.login()
try:
    print("Logged in, now getting Account details")
    status, accounts = trader.get_model("Account")
    account_id = accounts['accounts'][0]['accountId']
    print("Opening a trade now -USD/JPY 10 lots on %s"  % account_id)
    status, response = trader.open_trade(account_id, "USD/JPY", True, 10)
    if status is True:
        print("Open trade response: ", response)
        status, positions = trader.get_model("OpenPosition")
        print("Positions: ", positions)
        status, response = trader.close_all_for_symbol(account_id, True, "USD/JPY", "AtMarket", "GTC")
        print("Close All result:\n\n", status, response, "\n\n")
        status, positions = trader.get_model("OpenPosition")
        print("Positions: ", positions)

except Exception as e:
    print str(e)
