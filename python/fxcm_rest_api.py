import requests
from socketIO_client import SocketIO
import logging
import json
import uuid
import threading
from dateutil.parser import parse
from datetime import datetime
import time


def isInt(v):
    v = str(v).strip()
    return v=='0' or (v if v.find('..') > -1 else v.lstrip('-+').rstrip('0').rstrip('.')).isdigit()

class Trader(object):
    '''FXCM REST API abstractor.
    Obtain a new instance of this class and use that to do all trade and account actions.
    '''
    def __init__(self, user, password, environment, messageHandler=None):
        self.socketIO = None
        self.updates = {}
        self.symbols = {}
        self.symbol_info = {}
        self.user = user
        self.password = password
        self.env = environment
        if messageHandler is not None:
            self.message_handler = messageHandler
        else:
            self.message_handler = self.on_message
        self._log_init()
        self.list = CONFIG.get('subscription_list', [])
        self.environment = self._get_config(environment)
        #self.login()

    def login(self):
        '''
        Once you have an instance, run this method to log in to the service. Do this before any other calls
        :return: None
        '''
        status, auth_response = self._authenticate()
        if status:
            self.access_token = auth_response
            self.socketIO = SocketIO(self.environment.get("trading"), self.environment.get("port"),
                                     params={'access_token': self.access_token})
            self.socketIO.on('connect', self.on_connect)
            self.socketIO.on('disconnect', self.on_disconnect)
            self._socketIO_thread = threading.Thread(target=self.socketIO.wait)
            self._socketIO_thread.daemon = True
            self._socketIO_thread.start()

    def _authenticate(self):
        auth_params = {
            'client_id': CONFIG.get("authentication", {}).get("client_id"),
            'client_secret': CONFIG.get("authentication", {}).get("client_secret"),
            'grant_type': 'password',
            'username': self.user,
            'password': self.password
        }
        post_resp = requests.post(self.environment.get("auth", ""), headers=HEADERS, data=auth_params)
        data = post_resp.json()
        tmp_access_token = data["access_token"]
        if post_resp.status_code == 200:
            try:
                status, response = self.send('/authenticate', {'client_id': 'TRADING',
                                                                    'access_token': tmp_access_token })
            except Exception as e:
                status = False
                self.logger.fatal("Could not authenticate! " + str(e))
                return status, e
            if status is True:
                return True, response["access_token"]
            else:
                return False, "Trading authentication failed. Response code =" + str(response)
        else:
            return False, "OAuth2 authentication failed. Response code =" + str(post_resp.status_code)

    def _send_request(self, method, command, params):
        headers = HEADERS
        headers['User-Agent'] =  'request'
        if self.socketIO != None and self.socketIO.connected:
            params["socket_id"] = self.socketIO._engineIO_session.id
            params["access_token"] = self.access_token
        self.logger.info( self.environment.get("trading")  + command + str(params))
        if method == 'get':
            rresp = requests.get(self.environment.get("trading")  + command, params=params)
        else:
            rresp = requests.post(self.environment.get("trading") + command, headers=headers, data=params)
        if rresp.status_code == 200:
            data = rresp.json()
            if data["response"]["executed"] is True:
                return True, data
            return False, data["response"]["error"]
        else:
            return False, rresp.status_code

    def _get_config(self, environment):
        ret =CONFIG.get("environments", {}).get(environment, {})
        if ret == {}:
            self.logger.error("No configuration found. Please call your trade object with 'get_config(environment)'.")
            self.logger.error("Environments are prod, dev or qa.")
        return ret

    def _log_init(self):
        self.logger = logging.getLogger(self.user + "_" + self.env + "_" +str(uuid.uuid4())[:8])        
        self.ch = logging.StreamHandler()
        self.set_log_level(DEBUGLEVEL)   
        formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
        # add formatter to ch
        self.ch.setFormatter(formatter)
        self.logger.addHandler(self.ch)

    def set_log_level(self, level):
        '''
        set the logging level of the specific instance. Levels are DEBUG, INFO, WARNING, ERROR, CRITICAL
        :param level: Defaults to ERROR if log level is undefined

        :return: None
        '''
        self.logger.setLevel(LOGLEVELS.get(level, "ERROR"))
        self.ch.setLevel(LOGLEVELS.get(level, "ERROR"))

    def on_connect(self):
        '''
        Actions to be preformed on login. By default will subscribe to updates for items defined in subscription_list
        subscription_list is in the json config with options explained there
        If messageHandler was passed on instantiation, that will be used to handle all messages.
        Alternatively, this method can be overridden before login is called to provide different on_connect
        functionality.

        :return: None
        '''
        self.logger.info('Websocket connected: ' + self.socketIO._engineIO_session.id)
        status, response = self.send('/trading/subscribe', {'models': self.list})
        if status is True:
            for item in self.list:
                self.socketIO.on(item, self.message_handler)
        else:
            self.logger.error("Error processing request: /trading/subscribe:" + str(response))
        # Obtain and store the list of instruments in the symbol_info dict
        status, response = self.get_model("Offer")
        if status is True:
            for item in response['offers']:
                self.symbol_info[item['currency']] = item

    def on_disconnect(self):
        '''
        Simply logs info of the socket being closed. Override to add functionality

        :return: None
        '''
        self.logger.info("Websocket closed")

    def register_handler(self, message, handler):
        '''
        Register a callback handler for a specified message type

        :param message: string
        :param handler: function
        :return: None
        '''
        self.socketIO.on(message, handler)

    def on_price_update(self, msg):
        '''
        Sample price handler. If on_price_update is registered for a symbol, it will update the symbol's values (stored
        in a symbol hash) with that price update.
        symbol hash.

        :return: none
        '''
        md = json.loads(msg)
        self.symbols[md["Symbol"]] = md

    def on_message(self, msg):
        '''
        Sample generic message handling. Will update that specific message type with the latest message

        :return:
        '''
        message = json.loads(msg)
        self.updates[message["t"]] = message

    def send(self, location, params, method='post'):
        '''
        Method to send REST requests to the API

        :param location: eg. /subscribe
        :param params:  eg. {"pairs": "USD/JPY"}
        :param method: GET, POST, DELETE, PATCH
        :return: status Boolean, response String
        '''
        try:
            status, response = self._send_request(method, location, params)
        except Exception as e:
            self.logger.error("Failed to send request [%s]: %s" % (params, e))
            status = False
            response = str(e)
        return status, response

    def subscribe_symbol(self, instrument):
        '''
        Subscribe to given instrument

        :param instrument:
        :return: status Boolean, response String
        '''
        return self.send("/subscribe", {"pairs": instrument})

    def unsubscribe_symbol(self, instrument):
        '''
        Unsubscribe from instrument updates

        :param instrument:
        :return: status Boolean, response String
        '''
        return self.send("/unsubscribe", {"pairs": instrument})

    def subscribe(self, item):
        '''
        Subscribes to the updates of the data models. Update will be pushed to client via socketIO
        Model choices: 'Offer', 'OpenPosition', 'ClosedPosition', 'Order',  'Account',  'Summary',
        'LeverageProfile', 'Properties'

        :param item:
        :return: status Boolean, response String
        '''
        return self.send("/trading/subscribe", {"models": item})

    def unsubscribe(self, item):
        '''
        Unsubscribe from model ["Offer","Account","Order","OpenPosition","Summary","Properties"]

        :param item:
        :return: status Boolean, response String
        '''
        return self.send("/trading/unsubscribe", {"models": item})

    def get_model(self, item):
        '''
        Gets current content snapshot of the specified data models.
        Model choices: 'Offer', 'OpenPosition', 'ClosedPosition', 'Order', 'Summary', 'LeverageProfile',
        'Account', 'Properties'

        :param item:
        :return: status Boolean, response String
        '''
        return self.send("/trading/get_model", {"models": item}, "get")

    def change_password(self, oldpwd, newpwd):
        '''
        Change user password

        :param oldpwd:
        :param newpwd:
        :return: status Boolean, response String
        '''
        return self.send("/trading/changePassword", {"oldPswd": oldpwd, "newPswd": newpwd, "confirmNewPswd": newpwd})

    def permissions(self):
        '''
        Gets the object which defines permissions for the specified account identifier and symbol.
        Each property of that object specifies the corresponding permission ("createEntry", "createMarket",
        "netStopLimit", "createOCO" and so on).
        The value of the property specifies the permission status ("disabled", "enabled" or "hidden")


        :param item:
        :return: status Boolean, response String
        '''
        return self.send("/trading/permissions", {}, "get")

    def open_trade(self, account_id, symbol, is_buy, amount, rate=0, at_market=0, time_in_force="GTC",
                     order_type="AtMarket", stop=None, trailing_step=None, limit=None, is_in_pips=None):
        '''
        Create a Market Order with options for At Best or Market Range, and optional attached stops and limits.

        :param account_id:
        :param symbol:
        :param is_buy:
        :param amount:
        :param rate:
        :param at_market:
        :param time_in_force:
        :param order_type:
        :param stop: * Optional *
        :param trailing_step: * Optional *
        :param limit: * Optional *
        :param is_in_pips: * Optional *
        :return: status Boolean, response String
        '''
        if account_id is None or symbol is None or is_buy is None or amount is None:
            return False, "Failed to provide mandatory parameters"
        params = dict(account_id=account_id, symbol=symbol, is_buy=is_buy, amount=amount, rate=rate,
                      at_market=at_market, time_in_force=time_in_force, order_type=order_type)
        if stop is not None:
            params['stop'] = stop

        if trailing_step is not None:
            params['trailing_step'] = trailing_step

        if limit is not None:
            params['limit'] = limit

        if is_in_pips is not None:
            params['is_in_pips'] = is_in_pips
        return self.send("/trading/open_trade", params)

    def close_trade(self, trade_id, amount, at_market=0, time_in_force="GTC", order_type="AtMarket", rate=None):
        '''
        Close existing trade

        :param trade_id:
        :param amount:
        :param at_market:
        :param time_in_force:
        :param order_type:
        :param rate: * Optional *
        :return: status Boolean, response String
        '''
        if trade_id is None or amount is None or at_market is None or time_in_force is None or order_type is None:
            return False, "Failed to provide mandatory parameters"
        params = dict(trade_id=trade_id, amount=amount, at_market=at_market,
                      time_in_force=time_in_force, order_type=order_type)
        if rate is not None:
            params['rate'] = rate
        return self.send("/trading/close_trade", params)

    def change_order(self, order_id, rate, range, amount, trailing_step=None):
        '''
        Change order rate/amount

        :param order_id:
        :param rate:
        :param range:
        :param amount:
        :param trailing_step: * Optional *
        :return: status Boolean, response String
        '''
        if order_id is None or amount is None or rate is None or range is None:
            return False, "Failed to provide mandatory parameters"
        params = dict(order_id=order_id, rate=rate, range=range,
                      amount=amount)
        if trailing_step is not None:
            params['trailing_step'] = trailing_step
        return self.send("/trading/change_order", params)

    def delete_order(self, account_id, symbol, is_buy, amount, rate=0, at_market=0, time_in_force="GTC",
                     order_type="AtMarket", stop=None, trailing_step=None, limit=None, is_in_pips=None):
        '''
        Delete open order

        :param account_id:
        :param symbol:
        :param is_buy:
        :param amount:
        :param rate:
        :param at_market:
        :param time_in_force:
        :param order_type:
        :param stop: * Optional *
        :param trailing_step: * Optional *
        :param limit: * Optional *
        :param is_in_pips: * Optional *
        :return: status Boolean, response String
        '''
        if account_id is None or symbol is None or is_buy is None or amount is None:
            return False, "Failed to provide mandatory parameters"
        params = dict(account_id=account_id, symbol=symbol, is_buy=is_buy, amount=amount, rate=rate,
                      at_market=at_market, time_in_force=time_in_force, order_type=order_type)
        if stop is not None:
            params['stop'] = stop

        if trailing_step is not None:
            params['trailing_step'] = trailing_step

        if limit is not None:
            params['limit'] = limit

        if is_in_pips is not None:
            params['is_in_pips'] = is_in_pips
        return self.send("/trading/delete_order", params)

    def create_entry_order(self, account_id, symbol, is_buy, amount, limit, is_in_pips, order_type, time_in_force,
                           rate=0, stop=None, trailing_step=None):
        """
        Create a Limit Entry or a Stop Entry order.
        An order priced away from the market (not marketable) will be submitted as a Limit Entry order.
        An order priced through the market will be submitted as a Stop Entry order.

        If the market is at 1.1153 x 1.1159
        *	Buy Entry order @ 1.1165 will be processed as a Buy Stop Entry order.
        *	Buy Entry order @ 1.1154 will be processed as a Buy Limit Entry order

        :param account_id:
        :param symbol:
        :param is_buy:
        :param amount:
        :param limit:
        :param is_in_pips:
        :param order_type:
        :param time_in_force:
        :param rate:
        :param stop: * Optional *
        :param trailing_step: * Optional *
        :return: status Boolean, response String
        """
        if account_id is None or symbol is None or is_buy is None or amount is None or limit is None or \
                is_in_pips is None or order_type is None or time_in_force is None:
            return False, "Failed to provide mandatory parameters"
        params = dict(account_id=account_id, symbol=symbol, is_buy=is_buy, amount=amount, limit=limit,
                      is_in_pips=is_in_pips, time_in_force=time_in_force, order_type=order_type)
        if stop is not None:
            params['stop'] = stop

        if trailing_step is not None:
            params['trailing_step'] = trailing_step
        return self.send("/trading/create_entry_order", params)

    def simple_oco(self ,account_id, symbol, amount, is_in_pips, time_in_force, expiration, is_buy, rate, stop,
                   trailing_step,trailing_stop_step, limit, at_market, order_type, is_buy2, rate2, stop2,
                   trailing_step2, trailing_stop_step2, limit2):
        '''
        Create simple OCO

        :param account_id:
        :param symbol:
        :param amount:
        :param is_in_pips:
        :param time_in_force:
        :param expiration:
        :param is_buy:
        :param rate:
        :param stop:
        :param trailing_step:
        :param trailing_stop_step:
        :param limit:
        :param at_market:
        :param order_type:
        :param is_buy2:
        :param rate2:
        :param stop2:
        :param trailing_step2:
        :param trailing_stop_step2:
        :param limit2:
        :return: status Boolean, response String
        '''
        params = {}
        try:
            for k, v in locals().iteritems():
                if k != "self":
                    params[k] = v
            return self.send("/trading/simple_oco", params)
        except Exception as e:
            return False, str(e)

    def add_to_oco(self, orderIds, ocoBulkId):
        '''
        Add order(s) to an OCO

        :param orderIds:
        :param ocoBulkId:
        :return: status Boolean, response String
        '''
        return self.send("/trading/add_to_oco", {"orderIds": orderIds, "ocoBulkId": ocoBulkId})

    def remove_from_oco(self, orderIds):
        '''
        Remove order(s) from OCO

        :param orderIds:
        :return: status Boolean, response String
        '''
        return self.send("/trading/remove_from_oco", {"orderIds": orderIds})

    def edit_oco(self, ocoBulkId, addOrderIds, removeOrderIds):
        '''
        Edit an OCO

        :param ocoBulkId:
        :param addOrderIds:
        :param removeOrderIds:
        :return: status Boolean, response String
        '''
        return self.send("/trading/edit_oco", {"ocoBulkId": ocoBulkId, "addOrderIds": addOrderIds,
                                               "removeOrderIds": removeOrderIds})

    def change_trade_stop_limit(self, trade_id, is_stop, rate, is_in_pips, trailing_step):
        '''
        Creates/removes/changes the stop/limit order for the specified trade.
        If the current stop/limit rate for the specified trade is not set (is zero) and the new rate is not zero,
        then creates a new order.
        If the current stop/limit rate for the specified trade is set (is not zero), changes order rate
        (if the new rate is not zero) or deletes order (if the new rate is zero).


        :param trade_id:
        :param is_stop:
        :param rate:
        :param is_in_pips:
        :param trailing_step:
        :return: status Boolean, response String
        '''
        params = {}
        try:
            for k, v in locals().iteritems():
                if k != "self":
                    params[k] = v
            return self.send("/trading/change_trail_stop_limit", params)
        except Exception as e:
            return False, str(e)

    def change_order_stop_limit(self, order_id, is_stop, rate, is_in_pips, trailing_step):
        '''
        Creates/removes/changes the stop/limit order for the specified order.
        If the current stop/limit rate for the specified order is not set (is zero) and the new rate is not zero,
        then creates a new order.
        If the current stop/limit rate for the specified order is set (is not zero), changes order rate
        (if the new rate is not zero) or deletes order (if the new rate is zero).


        :param order_id:
        :param is_stop:
        :param rate:
        :param is_in_pips:
        :param trailing_step:
        :return: status Boolean, response String
        '''
        params = {}
        try:
            for k, v in locals().iteritems():
                if k != "self":
                    params[k] = v
            return self.send("/trading/change_order_stop_limit", params)
        except Exception as e:
            return False, str(e)

    def close_all_for_symbol(self, account_id, forSymbol, symbol, order_type, time_in_force):
        '''
        Closes all trades for the specified account and symbol by creating net quantity orders, if these orders are
        enabled, or by creating regular close orders otherwise.

        :param account_id:
        :param forSymbol: True/False
        :param symbol:
        :param order_type: AtMarket / MarketRange
        :param time_in_force: IOC GTC FOK DAY GTD
        :return: status Boolean, response String
        '''
        params = {}
        try:
            for k, v in locals().iteritems():
                if k != "self":
                    params[k] = v
            return self.send("/trading/close_all_for_symbol", params)
        except Exception as e:
            return False, str(e)

    def candles(self, instrument, period, num, From=None, To=None, datetime_fmt=None):
        '''
        Allow user to retrieve candle for a given instrument at a give time

        :param instrument: instrument_id or instrument. If instrument, will use mode information to convert to
                           instrument_id
        :param period: m1, m5, m15, m30, H1, H2, H3, H4, H6, H8, D1, W1, M1
        :param num: candles, max = 10,000
        :param From: timestamp or date/time string. Will conver to timestamp
        :param To: timestamp or date/time string. Will conver to timestamp
        :param datetime_fmt: Adding this optional parameter will add an additional field to the candle data with the
        timestamp converted to the datetime string provided. Example:
        .candles("USD/JPY", "m1", 3, datetime_fmt="%Y/%m/%d %H:%M:%S:%f")
        [1503694620, 109.321, 109.326, 109.326, 109.316, 109.359, 109.358, 109.362, 109.357, 28, '2017/08/26 05:57:00:000000']
        :return: status Boolean, response String
        '''
        try:
            initial_instrument = instrument
            if not isInt(instrument):
                instrument = self.symbol_info.get(instrument, {}).get('offerId', -1)
            if instrument < 0:
                raise ValueError("Instrument %s not found" % initial_instrument)
            if num > 10000:
                num = 10000
            params = dict(num=num)
            for k, v in {"From": From, "To": To}.iteritems():
                if v is not None:
                    if not isInt(v):
                        v = int(time.mktime(parse(v).timetuple()))
                    params[k] = v
                status, candle_data =  self.send("/candles/%s/%s" % (instrument, period), params, "get")
                if datetime_fmt is not None:
                    for i, candle in enumerate(candle_data['candles']):
                        candle_data['candles'][i].append(datetime.fromtimestamp(candle[0]).strftime(datetime_fmt))
            return status, candle_data
        except Exception as e:
            return False, str(e)



HEADERS = {
    'Accept': 'application/json',
    'Content-Type': 'application/x-www-form-urlencoded'
}
CONFIGFILE = "fxcm_rest.json"
CONFIG = {}
try:
    with open(CONFIGFILE, 'r') as f: 
        CONFIG = json.load(f)
except Exception as e:
    logging.error("Error loading config: " + e)
DEBUGLEVEL = CONFIG.get("debugLevel", "INFO")
LOGLEVELS = {"ERROR": logging.ERROR,
             "DEBUG": logging.DEBUG,
             "INFO": logging.INFO,
             "WARNING": logging.WARNING,
             "CRITICAL": logging.CRITICAL}