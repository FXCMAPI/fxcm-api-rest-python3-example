from collections import namedtuple
import requests
from socketIO_client import SocketIO
import logging
import json
import uuid
import threading
from dateutil.parser import parse
from datetime import datetime
import time
import types


def isInt(v):
    v = str(v).strip()
    return v == '0' or (v if v.find('..') > -1 else v.lstrip('-+').rstrip('0')
                                                     .rstrip('.')).isdigit()


def timestamp_to_string(timestamp, datetime_fmt="%Y/%m/%d %H:%M:%S:%f"):
    return datetime.fromtimestamp(timestamp).strftime(datetime_fmt)


class PriceUpdate(object):
    def __init__(self, bid=None, ask=None, high=None, low=None, updated=None,
                 symbol_info=None, parent=None):
        self.bid = bid
        self.ask = ask
        self.high = high
        self.low = low
        self.updated = updated
        self.output_fmt = "%r"
        self.parent = parent
        if symbol_info is not None:
            self.symbol_info = symbol_info
            self.offer_id = symbol_info['offerId']
            self.symbol = symbol_info['currency']
            precision = symbol_info['ratePrecision'] / 10.0
            self.output_fmt = "%s%0.1ff" % ("%", precision)

    def __repr__(self):
        try:
            date = timestamp_to_string(self.updated)
        except Exception:
            date = None
        output = "PriceUpdate(bid={0}, ask={0}," \
                 "high={0}, low={0}, updated=%r)".format(self.output_fmt)
        return output % (self.bid, self.ask, self.high,
                         self.low, date)

    def __print__(self):
        try:
            date = timestamp_to_string(self.updated)
        except Exception:
            date = None
        return "[%s => bid=%s, ask=%s, high=%s, low=%s]" % \
               (self.bid, self.ask, self.high, self.low, date)

    def unsubscribe(self):
        return self.parent.unsubscribe_symbol(self.symbol)

    def resubscribe(self):
        return self.parent.subscribe_symbol(self.symbol)


class Trader(object):
    '''FXCM REST API abstractor.
    Obtain a new instance of this class and use that
    to do all trade and account actions.
    '''

    def __init__(self, user, password, environment, messageHandler=None,
                 purpose='General', config_file="fxcm_rest.json"):
        self.config_file = config_file
        self.initialize()
        self.socketIO = None
        self.updates = {}
        self.symbols = {}
        self.symbol_info = {}
        self.symbol_id = {}
        self.account_id = None
        self.account_list = []
        self.accounts = {}
        self.orders_list = {}
        self.trades = {}
        self.subscriptions = {}
        self.open_list = []
        self.closed_list = []
        self.currency_exposure = {}
        self.user = user
        self.password = password
        self.env = environment
        self.purpose = purpose

        # for debugging - allows the suppression of specific messages
        # sent to self.Print.Helpful for when logging to console and
        # you want to keep log level, but remove some messages from the output
        self.ignore_output = []
        #####

        self.update_handlers = {"Offer": self.on_offer,
                                "Account": self.on_account,
                                "Order": self.on_order,
                                "OpenPosition": self.on_openposition,
                                "ClosedPosition": self.on_closedposition,
                                "Summary": self.on_summary,
                                "LeverageProfile": self.on_leverageprofile,
                                "Properties": self.on_properties}

        if messageHandler is not None:
            self.message_handler = self.add_method(messageHandler)
        else:
            self.message_handler = self.on_message
        self._log_init()
        self.list = self.CONFIG.get('subscription_list', [])
        self.environment = self._get_config(environment)
        # self.login()

    def Print(self, message, message_type=None, level='INFO'):
        loggers = dict(INFO=self.logger.info,
                       DEBUG=self.logger.debug,
                       WARNING=self.logger.warning,
                       ERROR=self.logger.error,
                       CRITICAL=self.logger.critical)
        if message_type is None or message_type not in self.ignore_output:
            loggers[level](message)

    def add_method(self, method):
        '''
        Returns a method suitable for addition to the instance.
        Can be used to override methods without subclassing.
        self.on_connect = self.add_method(MyConnectMethodHandler)
        :param method:
        :return: instance method
        '''
        return types.MethodType(method, self)

    def _authenticate(self):
        auth_params = {
            'client_id': self.CONFIG.get("authentication", {})
                                    .get("client_id"),
            'client_secret': self.CONFIG.get("authentication", {})
            .get("client_secret"),
            'grant_type': 'password',
            'username': self.user,
            'password': self.password
        }
        post_resp = requests.post(self.environment.get(
            "auth", ""), headers=self.HEADERS, data=auth_params)
        if post_resp.status_code == 200:
            data = post_resp.json()
            tmp_access_token = data["access_token"]
            try:
                response = self.send('/authenticate',
                                     {'client_id': 'TRADING',
                                      'access_token': tmp_access_token})
            except Exception as e:
                status = False
                self.logger.fatal("Could not authenticate! " + str(e))
                return self.__return(status, e)
            if response['status'] is True:
                return self.__return(True, response["access_token"])
            else:
                return self.__return(False, "Trading authentication failed. \
                                             Response code =" + str(response))
        else:
            return self.__return(False, "OAuth2 authentication failed. \
                                         Response code =" +
                                        str(post_resp.status_code))

    def login(self):
        '''
        Once you have an instance, run this method to log in to the service.
        Do this before any other calls
        :return: Dict
        '''
        self.access_token = None
        self.socketIO = None
        auth_response = self._authenticate()
        if auth_response['status']:
            self.access_token = auth_response['data']
            self.socketIO = SocketIO(self.environment.get("trading"),
                                     self.environment.get("port"),
                                     params={'access_token':
                                             self.access_token})
            self.socketIO.on('connect', self.on_connect)
            self.socketIO.on('disconnect', self.on_disconnect)
            # time.sleep(2)            
            accounts = self.get_model("Account").get('accounts', {})
            self.account_list = [a['accountId'] for a in accounts]
            self.account_id = None
            for account in accounts:
                account_id = account['accountId']
                self.accounts[account_id] = account
                if self.account_id is None and account_id != '':
                    self.account_id = account_id
            thread_name = self.user + self.env + self.purpose
            for thread in threading.enumerate():
                if thread.name == thread_name:
                    thread.keepGoing = False
            self._socketIO_thread = threading.Thread(target=self.socketIO.wait)
            self._socketIO_thread.setName(thread_name)
            self._socketIO_thread.keepGoing = True
            self._socketIO_thread.setDaemon(True)
            self._socketIO_thread.start()
            return self.__return(True, auth_response)
        else:
            return self.__return(False, auth_response)

    def logout(self):
        '''
        Unsubscribes from all subscribed items and logs out.
        :return:
        '''
        for item in self.subscriptions.keys():
            self.subscriptions.pop(item)
            self.socketIO.off(item)
        self.send("/logout")

    def _loop(self):
        while self._socketIO_thread.keepGoing:
            self.socketIO.wait(1)
        # self._socketIO_thread = threading.Thread(target=self.socketIO.wait)
        # self._socketIO_thread.setName(self.user + self.env)
        # self._socketIO_thread.setDaemon(True)
        # self._socketIO_thread.start()

    def __exit__(self, *err):
        pass

    def __enter__(self):
        return self

    def __return(self, status, data):
        ret_value = {'status': status}
        if type(data) == dict:
            ret_value.update(data)
        else:
            ret_value.update({'data': data})
        return ret_value

    def _send_request(self, method, command, params, additional_headers={}):
        headers = self.HEADERS
        headers['User-Agent'] = 'request'
        # headers.update(additional_headers)
        if self.socketIO is not None and self.socketIO.connected:
            params["socket_id"] = self.socketIO._engineIO_session.id
            params["access_token"] = self.access_token
        self.logger.info(self.environment.get(
            "trading") + command + str(params))
        if method == 'get':
            rresp = requests.get(self.environment.get(
                "trading") + command, params=params)
        else:
            rresp = requests.post(self.environment.get(
                "trading") + command, headers=headers, data=params)
        if rresp.status_code == 200:
            data = rresp.json()
            if data["response"]["executed"] is True:
                return self.__return(True, data)
            return self.__return(False, data["response"]["error"])
        else:
            return self.__return(False, rresp.status_code)

    def send(self, location, params={}, method='post', additional_headers={}):
        '''
        Method to send REST requests to the API

        :param location: eg. /subscribe
        :param params:  eg. {"pairs": "USD/JPY"}
        :param method: GET, POST, DELETE, PATCH
        :return: response Dict
        '''
        try:
            response = self._send_request(
                method, location, params, additional_headers)
            return response
        except Exception as e:
            self.logger.error("Failed to send request [%s]: %s" % (params, e))
            status = False
            response = str(e)
            return self.__return(status, response)

    def _get_config(self, environment):
        ret = self.CONFIG.get("environments", {}).get(environment, {})
        if ret == {}:
            self.logger.error(
                "No self.CONFIGuration found. Please call your trade object with\
                 'get_self.CONFIG(environment)'.")
            self.logger.error("Environments are prod, dev or qa.")
        return ret

    def _log_init(self):
        self.logger = logging.getLogger(
            self.user + "_" + self.env + "_" + str(uuid.uuid4())[:8])
        self.ch = logging.StreamHandler()
        self.set_log_level(self.debug_level)
        formatter = logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(message)s')
        # add formatter to ch
        self.ch.setFormatter(formatter)
        self.logger.addHandler(self.ch)

    def _forget(self, subscribed_item):
        if subscribed_item in self.subscriptions:
            try:
                self.subscriptions.pop(subscribed_item)
            except Exception:
                pass

    def set_log_level(self, level):
        '''
        set the logging level of the specific instance.
        Levels are DEBUG, INFO, WARNING, ERROR, CRITICAL
        :param level: Defaults to ERROR if log level is undefined

        :return: None
        '''
        self.logger.setLevel(self.LOGLEVELS.get(level, "ERROR"))
        self.ch.setLevel(self.LOGLEVELS.get(level, "ERROR"))

    def _add_method(self):
        pass

    def on_connect(self):
        '''
        Actions to be preformed on login. By default will subscribe to updates
        for items defined in subscription_list. subscription_list is in the
        json self.CONFIG with options explained there. If messageHandler was
        passed on instantiation, that will be used to handle all messages.
        Alternatively, this method can be overridden before login is called to
        provide different on_connect functionality.

        :return: None
        '''
        self.logger.info('Websocket connected: ' +
                         self.socketIO._engineIO_session.id)
        self.get_offers()
        # status, response = self.send('/trading/subscribe',
        #                              {'models': self.list})
        for item in self.list:
            handler = self.update_handlers.get(item, None)
            if handler is None:
                self.subscribe(item)
            else:
                self.subscribe(item, handler)
# Obtain and store the list of instruments in the symbol_info dict        

    def get_offers(self):
        response = self.get_model("Offer")
        if response['status'] is True:
            for item in response['offers']:
                self.symbol_info[item['currency']] = item
                self.symbol_id[item['offerId']] = item['currency']

    def on_disconnect(self):
        '''
        Simply logs info of the socket being closed.
        Override to add functionality

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
        Sample price handler. If on_price_update is registered for a symbol,
        it will update the symbol's values (stored in a symbol hash) with
        that price update.symbol hash.

        :return: none
        '''
        try:
            md = json.loads(msg)
            symbol = md["Symbol"]
            symbol_info = self.symbol_info.get(symbol, {})
            p_up = dict(symbol_info=self.symbol_info[symbol], parent=self)
            self.symbols[symbol] = self.symbols.get(symbol, PriceUpdate(p_up,
                                                    symbol_info=symbol_info))
            self.symbols[symbol].bid, self.symbols[symbol].ask,\
                self.symbols[symbol].high,\
                self.symbols[symbol].low = md['Rates']
            self.symbols[symbol].updated = md['Updated']
        except Exception as e:
            self.logger.error("Can't handle price update: " + str(e))

    def on_offer(self, msg):
        message = json.loads(msg)
        self.Print("Offer Update:" + message, "Offer", "INFO")

    def on_account(self, msg):
        message = json.loads(msg)
        account_id = message['accountId']
        self.accounts[account_id] = self.accounts.get(account_id, {})
        self.accounts[account_id].update(message)
        # self.Print("Account Update:" + msg, "Account", "INFO")

    def on_order(self, msg):
        message = json.loads(msg)
        order_id = message.get('orderId', '')
        self.orders_list[order_id] = self.orders_list.get(order_id,
                                                         {'actions': []})
        if "action" in message:
            self.orders_list[order_id]['actions'].append(message)
        self.orders_list[order_id].update(message)
        self.Print("Order Update:" + msg, "Order", "INFO")

    def on_openposition(self, msg):
        message = json.loads(msg)
        self.Print("OpenPosition Update:" + msg, "OpenPosition", "INFO")

    def on_closedposition(self, msg):
        message = json.loads(msg)
        self.Print("ClosedPosition Update:" + msg,
                   "ClosedPosition", "INFO")

    def on_summary(self, msg):
        message = json.loads(msg)
        self.Print("Summary Update:" + msg, "Summary", "INFO")

    def on_properties(self, msg):
        message = json.loads(msg)
        if "offerId" in message:
            message['symbol'] = self.symbol_id[message['offerId']]
        self.Print("Property Update:" + msg, "Property", "INFO")

    def on_leverageprofile(self, msg):
        message = json.loads(msg)
        self.Print("LeverageProfile Update:" + msg,
                   "LeverageProfile", "INFO")

    def on_message(self, msg):
        '''
        Sample generic message handling.
        Will update that specific message type with the latest message

        :return:
        '''
        self.Print(msg, -1, "INFO")

    @property
    def summary(self):
        '''
        Provides a summary snapshot ofthe account
        '''
        return self.get_model("Summary").get('summary', [])

    @property
    def offers(self):
        return self.get_model("Offer").get('offers', [])

    @property
    def open_positions(self):
        return self.get_model('OpenPosition').get('open_positions', [])

    @property
    def closed_positions(self):
        return self.get_model('ClosedPosition').get('closed_positions', [])

    @property
    def orders(self):
        return self.get_model('Order').get('orders', [])

    @property
    def leverage_profile(self):
        return self.get_model("LeverageProfile").get('leverage_profile', [])

    @property
    def properties(self):
        return self.get_model("Properties").get('properties', [])

    def subscribe_symbol(self, instruments, handler=None):
        '''
        Subscribe to given instrument

        :param instruments:
        :return: response Dict
        '''
        handler = handler or self.on_price_update
        if type(instruments) is list:
            print("This was a list")
            for instrument in instruments:
                self.subscriptions[instrument] = instrument
                self.socketIO.on(instrument, handler)
        else:
            self.subscriptions[instruments] = instruments
            self.socketIO.on(instruments, handler)
        return self.send("/subscribe", {"pairs": instruments},
                         additional_headers={'Transfer-Encoding': "chunked"})

    def unsubscribe_symbol(self, instruments,
                           headers={'Transfer-Encoding': "chunked"}):
        '''
        Unsubscribe from instrument updates

        :param instruments:
        :return: response Dict
        '''
        if type(instruments) is list:
            for instrument in instruments:
                self._forget(instrument)
                self.socketIO.off(instrument)
        else:
            self.socketIO.off(instruments)
            self._forget(instruments)
        return self.send("/unsubscribe", {"pairs": instruments})

    def subscribe(self, items, handler=None):
        '''
        Subscribes to the updates of the data models.
        Update will be pushed to client via socketIO
        Model choices: 'Offer', 'OpenPosition', 'ClosedPosition',
        'Order',  'Account',  'Summary', 'LeverageProfile', 'Properties'

        :param item:
        :return: response Dict
        '''
        handler = handler or self.on_message

        response = self.send("/trading/subscribe", {"models": items})
        if response['status'] is True:
            if type(items) is list:
                for item in items:
                    self.socketIO.on(item, handler)
            else:
                self.socketIO.on(items, handler)
        else:
            self.logger.error(
                "Error processing /trading/subscribe:" + str(response))
        return response

    def unsubscribe(self, items):
        '''
        Unsubscribe from model
        ["Offer","Account","Order","OpenPosition","Summary","Properties"]

        :param item:
        :return: response Dict
        '''
        if type(items) is list:
            for item in items:
                self._forget(item)
                self.socketIO.off(item)
        else:
            self._forget(items)
            self.socketIO.off(items)
        return self.send("/trading/unsubscribe", {"models": item})

    def get_model(self, item):
        '''
        Gets current content snapshot of the specified data models.
        Model choices:
        'Offer', 'OpenPosition', 'ClosedPosition', 'Order', 'Summary',
        'LeverageProfile', 'Account', 'Properties'

        :param item:
        :return: response Dict
        '''
        return self.send("/trading/get_model", {"models": item}, "get")

    def change_password(self, oldpwd, newpwd):
        '''
        Change user password

        :param oldpwd:
        :param newpwd:
        :return: response Dict
        '''
        return self.send("/trading/changePassword", {"oldPswd": oldpwd,
                                                     "newPswd": newpwd,
                                                     "confirmNewPswd": newpwd})

    def permissions(self):
        '''
        Gets the object which defines permissions for the specified account
        identifier and symbol. Each property of that object specifies the
        corresponding permission ("createEntry", "createMarket",
        "netStopLimit", "createOCO" and so on).
        The value of the property specifies the permission status
        ("disabled", "enabled" or "hidden")


        :param item:
        :return: response Dict
        '''
        return self.send("/trading/permissions", {}, "get")

    def open_trade(self, account_id, symbol, is_buy, amount, rate=0,
                   at_market=0, time_in_force="GTC", order_type="AtMarket",
                   stop=None, trailing_step=None, limit=None, is_in_pips=None):
        '''
        Create a Market Order with options for At Best or Market Range,
        and optional attached stops and limits.

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
        :return: response Dict
        '''
        if None in [account_id, symbol, is_buy, amount]:
            ret = "Failed to provide mandatory parameters"
            return self.__return(False, ret)

        is_buy = 'true' if is_buy else 'false'
        print(is_buy)
        params = dict(account_id=account_id, symbol=symbol,
                      is_buy=is_buy, amount=amount, rate=rate,
                      at_market=at_market, time_in_force=time_in_force,
                      order_type=order_type)
        if stop is not None:
            params['stop'] = stop

        if trailing_step is not None:
            params['trailing_step'] = trailing_step

        if limit is not None:
            params['limit'] = limit

        if is_in_pips is not None:
            params['is_in_pips'] = is_in_pips
        return self.send("/trading/open_trade", params)

    def close_trade(self, trade_id, amount, at_market=0,
                    time_in_force="GTC", order_type="AtMarket", rate=None):
        '''
        Close existing trade

        :param trade_id:
        :param amount:
        :param at_market:
        :param time_in_force:
        :param order_type:
        :param rate: * Optional *
        :return: response Dict
        '''
        if None in [trade_id, amount, at_market, time_in_force, order_type]:
            ret = "Failed to provide mandatory parameters"
            return self.__return(False, ret)
        params = dict(trade_id=trade_id, amount=amount, at_market=at_market,
                      time_in_force=time_in_force, order_type=order_type)
        if rate is not None:
            params['rate'] = rate
        return self.send("/trading/close_trade", params)

    def change_order(self, order_id, rate, rng, amount, trailing_step=None):
        '''
        Change order rate/amount

        :param order_id:
        :param rate:
        :param range:
        :param amount:
        :param trailing_step: * Optional *
        :return: response Dict
        '''
        if None in [order_id, amount, rate, rng]:
            ret = "Failed to provide mandatory parameters"
            return self.__return(False, ret)
        params = dict(order_id=order_id, rate=rate, range=rng,
                      amount=amount)
        if trailing_step is not None:
            params['trailing_step'] = trailing_step
        return self.send("/trading/change_order", params)

    def delete_order(self, account_id, symbol, is_buy, amount, rate=0,
                     at_market=0, time_in_force="GTC", order_type="AtMarket",
                     stop=None, trailing_step=None, limit=None,
                     is_in_pips=None):
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
        :return: response Dict
        '''
        if None in [account_id, symbol, is_buy, amount]:
            ret = "Failed to provide mandatory parameters"
            return self.__return(False, ret)
        params = dict(account_id=account_id, symbol=symbol, is_buy=is_buy,
                      amount=amount, rate=rate, at_market=at_market,
                      time_in_force=time_in_force, order_type=order_type)
        if stop is not None:
            params['stop'] = stop

        if trailing_step is not None:
            params['trailing_step'] = trailing_step

        if limit is not None:
            params['limit'] = limit

        if is_in_pips is not None:
            params['is_in_pips'] = is_in_pips
        return self.send("/trading/delete_order", params)

    def create_entry_order(self, account_id, symbol, is_buy, amount, limit,
                           is_in_pips, order_type, time_in_force,
                           rate=0, stop=None, trailing_step=None):
        """
        Create a Limit Entry or a Stop Entry order.
        An order priced away from the market (not marketable)
        will be submitted as a Limit Entry order. An order priced through the
        market will be submitted as a Stop Entry order.

        If the market is at 1.1153 x 1.1159
        *   Buy Entry order @ 1.1165 will be processed as a
            Buy Stop Entry order.
        *   Buy Entry order @ 1.1154 will be processed as a
            Buy Limit Entry order

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
        :return: response Dict
        """
        if None in [account_id, symbol, is_buy, amount, limit,
                    is_in_pips, order_type, time_in_force]:
            ret = "Failed to provide mandatory parameters"
            return self.__return(False, ret)
        params = dict(account_id=account_id, symbol=symbol, is_buy=is_buy,
                      amount=amount, limit=limit, is_in_pips=is_in_pips,
                      time_in_force=time_in_force, order_type=order_type)
        if stop is not None:
            params['stop'] = stop

        if trailing_step is not None:
            params['trailing_step'] = trailing_step
        return self.send("/trading/create_entry_order", params)

    def simple_oco(self, account_id, symbol, amount, is_in_pips, time_in_force,
                   expiration, is_buy, rate, stop, trailing_step,
                   trailing_stop_step, limit, at_market, order_type, is_buy2,
                   rate2, stop2, trailing_step2, trailing_stop_step2, limit2):
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
        :return: response Dict
        '''
        items = locals().items()
        params = {}
        try:
            for k, v in items:
                if k != "self":
                    params[k] = v
            return self.__return(self.send("/trading/simple_oco", params))
        except Exception as e:
            return (False, str(e))

    def add_to_oco(self, orderIds, ocoBulkId):
        '''
        Add order(s) to an OCO

        :param orderIds:
        :param ocoBulkId:
        :return: response Dict
        '''
        return self.send("/trading/add_to_oco", {"orderIds": orderIds,
                                                 "ocoBulkId": ocoBulkId})

    def remove_from_oco(self, orderIds):
        '''
        Remove order(s) from OCO

        :param orderIds:
        :return: response Dict
        '''
        return self.send("/trading/remove_from_oco", {"orderIds": orderIds})

    def edit_oco(self, ocoBulkId, addOrderIds, removeIds):
        '''
        Edit an OCO

        :param ocoBulkId:
        :param addOrderIds:
        :param removeOrderIds:
        :return: response Dict
        '''
        return self.send("/trading/edit_oco", {"ocoBulkId": ocoBulkId,
                                               "addOrderIds": addOrderIds,
                                               "removeOrderIds": removeIds})

    def change_trade_stop_limit(self, trade_id, is_stop,
                                rate, is_in_pips, trailing_step):
        '''
        Creates/removes/changes the stop/limit order for the specified trade.
        If the current stop/limit rate for the specified trade is not set
        (is zero) and the new rate is not zero, then creates a new order.
        If the current stop/limit rate for the specified trade is set
        (is not zero), changes order rate (if the new rate is not zero) or
        deletes order (if the new rate is zero).


        :param trade_id:
        :param is_stop:
        :param rate:
        :param is_in_pips:
        :param trailing_step:
        :return: response Dict
        '''
        items = locals().items()
        params = {}
        try:
            for k, v in items:
                if k != "self":
                    params[k] = v
            return self.send("/trading/change_trail_stop_limit", params)
        except Exception as e:
            return self.__return(False, str(e))

    def change_order_stop_limit(self, order_id, is_stop,
                                rate, is_in_pips, trailing_step):
        '''
        Creates/removes/changes the stop/limit order for the specified order.
        If the current stop/limit rate for the specified order is not set
        (is zero) and the new rate is not zero,
        then creates a new order.
        If the current stop/limit rate for the specified order is set
        (is not zero), changes order rate (if the new rate is not zero)
        or deletes order (if the new rate is zero).


        :param order_id:
        :param is_stop:
        :param rate:
        :param is_in_pips:
        :param trailing_step:
        :return: response Dict
        '''
        items = locals().items()
        params = {}
        try:
            for k, v in items:
                if k != "self":
                    params[k] = v
            return self.send("/trading/change_order_stop_limit", params)
        except Exception as e:
            return self.__return(False, str(e))

    def close_all_for_symbol(self, account_id, forSymbol,
                             symbol, order_type, time_in_force):
        '''
        Closes all trades for the specified account and symbol by creating net
        quantity orders, if these orders are enabled, or by creating regular
        close orders otherwise.

        :param account_id:
        :param forSymbol: True/False
        :param symbol:
        :param order_type: AtMarket / MarketRange
        :param time_in_force: IOC GTC FOK DAY GTD
        :return: response Dict
        '''
        items = locals().items()
        params = {}
        try:
            for k, v in items:
                if k != "self":
                    params[k] = v
            return self.send("/trading/close_all_for_symbol", params)
        except Exception as e:
            return self.__return(False, str(e))

    def get_candles(self, instrument, period, num,
                    From=None, To=None, dt_fmt=None):
        '''
        Allow user to retrieve candle for a given instrument at a give time

        :param instrument: instrument_id or instrument. If instrument, will
                           use mode information to convert to instrument_id
        :param period: m1, m5, m15, m30, H1, H2, H3, H4, H6, H8, D1, W1, M1
        :param num: candles, max = 10,000
        :param From: timestamp or date/time string. Will conver to timestamp
        :param To: timestamp or date/time string. Will conver to timestamp
        :param dt_fmt: Adding this optional parameter will add an additional
                       field to the candle data with the timestamp converted
                       to the datetime string provided. Example:
        .candles("USD/JPY", "m1", 3, datetime_fmt="%Y/%m/%d %H:%M:%S:%f")
        [1503694620, 109.321, 109.326, 109.326, 109.316, 109.359,
        109.358, 109.362, 109.357, 28, '2017/08/26 05:57:00:000000']
        :return: response Dict
        '''
        try:
            initial_instrument = instrument
            if not isInt(instrument):
                instrument = self.symbol_info.get(
                    instrument, {}).get('offerId', -1)
            if instrument < 0:
                raise ValueError("Instrument %s not found" %
                                 initial_instrument)
            if num > 10000:
                num = 10000
            params = dict(num=num)
            for k, v in {"From": From, "To": To}.items():
                if v is not None:
                    if not isInt(v):
                        v = int(time.mktime(parse(v).timetuple()))
                    params[k] = v
            candle_data = self.send("/candles/%s/%s" %
                                    (instrument, period), params, "get")
            headers = ['timestamp', 'bidopen', 'bidclose', 'bidhigh', 'bidlow',
                       'askopen', 'askclose', 'askhigh', 'asklow', 'tickqty']
            if dt_fmt is not None:
                headers.append("datestring")
                for i, candle in enumerate(candle_data['candles']):
                    candle_data['candles'][i].append(
                        datetime.fromtimestamp(candle[0]).strftime(dt_fmt))
            candle_data['headers'] = headers
            return self.__return(candle_data['status'], candle_data)
        except Exception as e:
            return (False, str(e))

    candles = get_candles

    def candles_as_dict(self, instrument, period, num,
                        From=None, To=None, dt_fmt=None):
        '''
        Allow user to retrieve candle for a given instrument at a give time
        as a dictionary.

        :param instrument: instrument_id or instrument. If instrument, will
                           use mode information to convert to instrument_id
        :param period: m1, m5, m15, m30, H1, H2, H3, H4, H6, H8, D1, W1, M1
        :param num: candles, max = 10,000
        :param From: timestamp or date/time string. Will conver to timestamp
        :param To: timestamp or date/time string. Will conver to timestamp
        :param dt_fmt: Adding this optional parameter will add an additional
                       field to the candle data with the timestamp converted
                       to the datetime string provided. Example:
        .candles("USD/JPY", "m1", 3, datetime_fmt="%Y/%m/%d %H:%M:%S:%f")
        [1503694620, 109.321, 109.326, 109.326, 109.316, 109.359,
        109.358, 109.362, 109.357, 28, '2017/08/26 05:57:00:000000']
        :return: response Dict
        '''
        try:
            candle_data = self.get_candles(
                instrument, period, num, From, To, dt_fmt)
            status = candle_data['status']
            if status is True:
                Headers = namedtuple('Headers', candle_data['headers'])
                candle_dict = map(Headers._make, candle_data['candles'])
                candle_data['candles'] = candle_dict
            return self.__return(status, candle_data)
        except Exception as e:
            return self.__return(False, str(e))

    def initialize(self):
        self.HEADERS = {
            'Accept': 'application/json',
            'Content-Type': 'application/x-www-form-urlencoded'
        }
        self.CONFIG = {}
        try:
            with open(self.config_file, 'r') as f:
                self.CONFIG = json.load(f)
        except Exception as e:
            logging.error("Error loading self.CONFIG: " + str(e))
        self.debug_level = self.CONFIG.get("DEBUGLEVEL", "ERROR")
        self.LOGLEVELS = {"ERROR": logging.ERROR,
                          "DEBUG": logging.DEBUG,
                          "INFO": logging.INFO,
                          "WARNING": logging.WARNING,
                          "CRITICAL": logging.CRITICAL}
