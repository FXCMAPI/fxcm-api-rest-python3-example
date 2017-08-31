# Python REST API

For a quick demo:
-----------------
1. Install python
2. Run: pip install -r requirements.txt
3. Change login and password in rest_client.py file
4. Within the fxcm_rest.json file:
  a. * Set log path via the logpath field
  b. * Set the authentication client_id and client_secret details.
  c. Set debugLevel if desired
  d. Set subscription lists if desired
5. In the fxcm_rest_client_sample.py file:
    a. Set your username, password and environment (prod/qa/dev)
    
## Details

This API exposes the methods of the REST API as a class, dealing with all of the common tasks 
involved with setting up connections and wiring callback listeners for you. In addition to that
there are a few convenience methods. 
A quick example is as follows;

    import fxcm_rest_api
    trader = fxcm_rest_api.Trader('username', 'password', 'environment')
    trader.login()
    
    #### Open Market Order
    # query account details and use the first account found
    status, accounts = trader.get_model("Account")
    account_id = accounts['accounts'][0]['accountId']
    # Open 10 lots on USD/JPY for the first account_id found.
    status, response = trader.open_trade(account_id, "USD/JPY", True, 10)
    if status:
    # close all USD/JPY trades.
      status, response = trader.close_all_for_symbol(account_id, True, "USD/JPY", "AtMarket", "GTC")
    
    #### Historical Data request
    status, basic = trader.candles("USD/JPY", "m1", 5)
    status, date_fmt = trader.candles("USD/JPY", "m1", 5, datetime_fmt="%Y/%m/%d %H:%M:%S")
    status, date_fmt_headers = trader.candles_as_dict("USD/JPY", "m1", 3, datetime_fmt="%Y/%m/%d %H:%M:%S")
    
    ##### Price subscriptions
    status, subscription_result = trader.subscribe_symbol("USD/JPY")
    
    # Define alternative price update handler and supply that.
    def pupdate(msg):
        print "Price update: ", msg
    status, subscription_result = trader.subscribe_symbol("USD/JPY", pupdate)
  
(All calls to candles allow either instrument name, or offerId. They also allow the From and To to be specified
as timestamp or a date/time format that will be interpreted ("2017/08/01 10:00", "Aug 1, 2017 10:00", etc.).
In addition to instrument_id, response, period_id and candles, a 'headers' field (not documented in the API notes)
is returned, representing the candle fields.)

basic

    for item in basic['candles']: 
        print item
    
    [1503694500, 109.317, 109.336, 109.336, 109.314, 109.346, 109.366, 109.373, 109.344, 72]
    [1503694560, 109.336, 109.321, 109.337, 109.317, 109.366, 109.359, 109.366, 109.354, 83]
    [1503694620, 109.321, 109.326, 109.326, 109.316, 109.359, 109.358, 109.362, 109.357, 28]
date_fmt

    for item in date_fmt['candles']:
        print item
    
    [1503694500, 109.317, 109.336, 109.336, 109.314, 109.346, 109.366, 109.373, 109.344, 72, '2017/08/26 05:55:00']
    [1503694560, 109.336, 109.321, 109.337, 109.317, 109.366, 109.359, 109.366, 109.354, 83, '2017/08/26 05:56:00']
    [1503694620, 109.321, 109.326, 109.326, 109.316, 109.359, 109.358, 109.362, 109.357, 28, '2017/08/26 05:57:00']
date_fmt_headers

    for item in date_fmt_headers['candles']: 
        print item
    
    Headers(timestamp=1503694620, bidopen=109.321, bidclose=109.326, bidhigh=109.326, bidlow=109.316, askopen=109.359, askclose=109.358, askhigh=109.362, asklow=109.357, tickqty=28, datestring='2017/08/26 05:57:00')
    Headers(timestamp=1503694680, bidopen=109.326, bidclose=109.312, bidhigh=109.326, bidlow=109.31, askopen=109.358, askclose=109.374, askhigh=109.376, asklow=109.358, tickqty=42, datestring='2017/08/26 05:58:00')
    Headers(timestamp=1503694740, bidopen=109.312, bidclose=109.312, bidhigh=109.312, bidlow=109.31, askopen=109.374, askclose=109.374, askhigh=109.374, asklow=109.372, tickqty=4, datestring='2017/08/26 05:59:00')
    
    for item in date_fmt_headers['candles']: 
        print "%s: Ask Close [%s], High Bid [%s] " % (item.datestring, item.askclose, item.bidhigh)
    
    2017/08/26 05:57:00: Ask Close [109.358], High Bid [109.326]
    2017/08/26 05:58:00: Ask Close [109.374], High Bid [109.326]
    2017/08/26 05:59:00: Ask Close [109.374], High Bid [109.312]
subscribe_symbol - default

    {u'Updated': 1504167080, u'Rates': [110.467, 110.488, 110.629, 110.156], u'Symbol': u'USD/JPY'}
    {u'Updated': 1504167081, u'Rates': [110.469, 110.49, 110.629, 110.156], u'Symbol': u'USD/JPY'}
subscribe_symbol - overridden

    Price update:  {"Updated":1504167248,"Rates":[110.446,110.468,110.629,110.156],"Symbol":"USD/JPY"}
    Price update:  {"Updated":1504167250,"Rates":[110.446,110.468,110.629,110.156],"Symbol":"USD/JPY"}
    

