"""
FXCM Trading RESTful API example.
"""
import json
import time
import requests
from socketIO_client import SocketIO
from prompt_toolkit import prompt
from threading import Thread
import signal
import sys
import io
from datetime import datetime

socketIO = None
UPDATES = {}
SYMBOLS = {}
COLLECTIONS = None
ACCESS_TOKEN = None

logFile = "./apiLog.txt"

def getEnv(e):
    if len(e) == 1:
        if e == "p":
            auth = 'https://www-beta2.fxcorporate.com/oauth/token'
            trading = 'https://api.fxcm.com'
            socket_port = 443
        elif e == "q":  
            auth = 'https://titan2x.fxcorporate.com/oauth/token'
            trading = 'https://titan3x.fxcorporate.com'
            socket_port = 443
        elif e == "d":
            auth = 'https://devtitan.fxcorporate.com:8080/oauth/token'
            trading = 'https://devtitan.fxcorporate.com:8088'
            socket_port = 8088
        else:
            print "Incorrect Environment Specified.  Enter p, q, or d"
            sys.exit(0)
    else:
        print "Incorrect Environment Specified.  Enter p, q, or d"
        sys.exit(0)

    return auth, trading, socket_port

def timestamp():
    output = str(datetime.now().strftime('%Y%m%d-%H:%M:%S.%f')[:-3])
    return output

def logging(mess, t):
    ts = timestamp()

    with io.FileIO(logFile, "a") as file:
        file.write('\n' +ts + ": " +t + " ==>"  +'\n')
        for key in mess:
                file.write(str(key) +" - " +str(mess[key]) +'\n')
                    
def request_processor(method, params):
    """ Trading server request help function. """
    if socketIO != None and socketIO.connected is True:
        params["socket_id"] = socketIO._engineIO_session.id
        params["access_token"] = ACCESS_TOKEN
    rresp = requests.get(TRADING_API_URL + method, params=params)
    if rresp.status_code == 200:
        data = rresp.json()
        if data["response"]["executed"] is True:
            return True, data
        return False, data["response"]["error"]
    else:
        return False, rresp.status_code

def post_request_processor(method, params):
    """ Trading server request help function. """
    if socketIO != None and socketIO.connected is True:
        params["socket_id"] = socketIO._engineIO_session.id
        params["access_token"] = ACCESS_TOKEN
    
    headers = {
    'User-Agent': 'request',
        'Accept': 'application/json',
        'Content-Type': 'application/x-www-form-urlencoded'
    }
    rresp = requests.post(TRADING_API_URL + method, headers=headers, data=params)
    if rresp.status_code == 200:
        data = rresp.json()
        if data["response"]["executed"] is True:
            return True, data
        return False, data["response"]["error"]
    else:
        return False, rresp.status_code

def authenticate(user, password):
    """ Authentication with trading server using aouth2 protocol. """
    headers = {
        'Accept': 'application/json',
        'Content-Type': 'application/x-www-form-urlencoded'
    }
    auth_params = {
        'client_id': 'Titan',
        'client_secret': 'qqq',
        'grant_type': 'password',
        'username': user,
        'password': password
    }
    post_resp = requests.post(AUTH_API_URL, headers=headers, data=auth_params)
    data = post_resp.json()
    tmp_access_token = data["access_token"]
    if post_resp.status_code == 200:
        status, response = post_request_processor('/authenticate', {
            'client_id': 'TRADING',
            'access_token': tmp_access_token
        })
        if status is True:
            return True, response["access_token"]
        else:
            return False, "Trading authentication failed. Response code =" + str(response)
    else:
        return False, "OAuth2 authentication failed. Response code =" + str(post_resp.status_code)

def on_price_update(msg):
    md = json.loads(msg)
    SYMBOLS[md["Symbol"]] = md
    logging(SYMBOLS, "SYMBOLS")

def on_message(msg):
    message = json.loads(msg)
    UPDATES[message["t"]] = message
    logging(UPDATES, "UPDATES")

def on_error(ws, error):
    print error

def on_close():
    print 'Websocket closed.'

def on_connect():
    print 'Websocket connected: ' + socketIO._engineIO_session.id
    ### Subscribe message updates
    status, response = post_request_processor('/trading/subscribe', {'models': list})
    if status is True:
        for item in list:
            socketIO.on(item, on_message)
    else:
        print "Error processing request: /trading/subscribe:", response
    ###
    ### Subscribe for prices
    ###
    symbol = 'USD/JPY'
    status, response = post_request_processor('/subscribe', {'pairs': symbol})
    if status is True:
        socketIO.on(symbol, on_price_update)
    else:
        print "Error processing request: /subscribe: ", response

def cli(args):
    while True:
        try:
            inp = prompt(u'> ')
        except KeyboardInterrupt:
            print "Press Ctrl+c again to quit."
            sys.exit(1)
        if not inp:
            continue
        try:
            if len(inp) > 3 and inp[0:3] == 'run':
                cmd = json.loads(inp[4:])
                command = cmd["c"]
                if command == 'book':
                    for symbol in SYMBOLS:
                        price = SYMBOLS[symbol]
                        print price

                elif command == 'show':
                    if cmd["opt"] == 'offers':
                        for offer in COLLECTIONS['offers']:
                            print '{}, {}, {}'.format(price['currency'], price['sell'], price['buy'])

                    elif cmd["opt"] == 'orders':
                        for order in COLLECTIONS['orders']:
                            print order

                    elif cmd["opt"] == 'updates':
                        for obj in UPDATES:
                            print obj

                elif command == 'subscribe':
                    for symbol in cmd["opt"]:
                        status, response = post_request_processor('/subscribe', {'pairs': symbol})
                        if status is True:
                            print response
                            socketIO.on(symbol, on_price_update)
                        else:
                            print "Error processing request: /subscribe: " + response

                elif command == 'unsubscribe':
                    for symbol in cmd["opt"]:                    
                        status, response = post_request_processor('/unsubscribe', {'pairs': symbol})
                        if status is False:
                            print "Error processing request: /unsubscribe: " + response

                elif command == 'market_order':
                    status, response = post_request_processor('/trading/open_trade', {
                        'account_id': cmd['account_id'],
                        'symbol': cmd['symbol'],
                        'is_buy': cmd['side'],
                        'rate': 0,
                        'amount': cmd['amount'],
                        'at_market': 0,
                        'order_type': 'AtMarket',
                        'time_in_force': cmd['time_in_force']
                    })
                    if status is True:
                        print 'Order has been executed: {}'.format(response)
                    else:
                        print 'Order execution error: {}'.format(response)
                        
                else:
                    print "Unknown command: " + command
            else:
                print 'Unknown command.'
        except ValueError:
            print 'Invalid command'

### Main

if __name__ == '__main__':
    if len(sys.argv) == 2:
        env = sys.argv[1]
        AUTH_API_URL, TRADING_API_URL, WEBSOCKET_PORT = getEnv(env)
    else:
        print "Incorrect Environment Specified.  Enter p, q, or d"
        sys.exit(0)

    status, auth_response = authenticate('ar', 'q')
    if status is True:
        ACCESS_TOKEN = auth_response
        print ACCESS_TOKEN
        socketIO = SocketIO(TRADING_API_URL, WEBSOCKET_PORT, params={'access_token': ACCESS_TOKEN})
        socketIO.on('connect', on_connect)
        socketIO.on('disconnec', on_close)
        ###
        list = ['Offer','Account','Order','OpenPosition','Summary','Properties']
        status, response = request_processor('/trading/get_model', {'models': list})
        if status is True:
                COLLECTIONS = response
                print COLLECTIONS["accounts"]
        ###
        thr = Thread(target=cli, args=(1,))
        try:
                thr.setDaemon(True)
                thr.start()
                socketIO.wait()
        except (KeyboardInterrupt, SystemExit):
                thr.join(0)
                sys.exit(1)
    else:
        print auth_response
