import os
import re
import time
import json
import requests
import threading
import traceback
from utils.json_manage import *
from utils.binance_key import *
from utils.config import *
from utils.telegram_lib import *
from datetime import datetime, timedelta
import dateutil.parser as dparser


ARTICLES_URL = 'https://www.binance.com/bapi/composite/v1/public/cms/article/catalog/list/query?catalogId=48&pageNo=1&pageSize=15'
ARTICLE      = 'https://www.binance.com/bapi/composite/v1/public/cms/article/detail/query?articleCode='

key_words = ['Futures', 'Isolated', 'Margin', 'Launchpool', 'Launchpad', 'Cross', 'Perpetual']
filter_List = ['body', 'type', 'catalogId', 'catalogName', 'publishDate']

file = 'res/announcements.json'
schedules_file = 'res/scheduled_order.json'
executed_trades_file = 'res/executed_trades.json'
executed_sells_file = 'res/executed_sells_trades.json'
coins_file = 'res/existing_coins.json'


existing_coins = []
executed_queque = []
current_buy_threads = []

cnf = load_config('conf/config.yml')
client = load_binance_creds(r'conf/auth.yml')

tsl_mode = cnf['TRADE_OPTIONS']['ENABLE_TSL']

if tsl_mode:
    sl = cnf['TRADE_OPTIONS']['TSL']
    tp = cnf['TRADE_OPTIONS']['TTP']

else:
    tp = cnf['TRADE_OPTIONS']['TP']
    sl = cnf['TRADE_OPTIONS']['SL']

pairing = cnf['TRADE_OPTIONS']['PAIRING']
ammount = cnf['TRADE_OPTIONS']['QUANTITY']
frequency = cnf['TRADE_OPTIONS']['RUN_EVERY']

test_mode = cnf['TRADE_OPTIONS']['TEST']
delay_mode = cnf['TRADE_OPTIONS']['CONSIDER_DELAY']
percentage = cnf['TRADE_OPTIONS']['PERCENTAGE']

regex = '\S{2,6}?/'+ pairing


def ping_binance():
    sum = 0
    for i in range(3):
        time_before = datetime.timestamp(datetime.now())
        client.ping()
        time_after = datetime.timestamp(datetime.now())
        sum += (time_after - time_before)
    return (sum / 3)


def getAllExistingCoins():
    global existing_coins
    if os.path.exists(coins_file):
        existing_coins = load_json(coins_file)
    else:
        allPairs = client.get_all_tickers()
        for coin in allPairs:
            if pairing in coin['symbol']:
                coin = re.sub( pairing, '', coin['symbol'])
                existing_coins.append(coin)
        save_json(coins_file, existing_coins)


####announcements

def get_Announcements():
    unfiltered_Articles = requests.get(ARTICLES_URL).json()['data']['articles']
    articles = []

    for article in unfiltered_Articles:
        flag = True
        #add reschedule logic here too
        for word in key_words:
            if word in article['title']:
                flag = False
        if flag:
            articles.append(article)        

    for article in articles:
        for undesired_Data in filter_List:
            if undesired_Data in article:
                del article[undesired_Data]
    
    return articles


def get_Pair_and_DateTime(ARTICLE_CODE):
    pairs = []
    try:
        new_Coin = requests.get(ARTICLE+ARTICLE_CODE).json()['data']['seoDesc']
        datetime = dparser.parse(new_Coin, fuzzy=True, ignoretz=True)
        raw_pairs = re.findall(regex, new_Coin)
        for pair in raw_pairs:
            print("===="+ pair)
            if not pair.split('/')[0] in existing_coins:
                pairs.append(pair.replace('/', ''))
        return [datetime, pairs]        
    except Exception as e:
        sendmsg("[WARNING] The article with url " + ARTICLE + ARTICLE_CODE + " and description " + new_Coin + " couldn't be parsed successfully.")
        sendmsg(f"Error log: {str(e)}")
        return None

####orders

def avFills(order):
    prices = 0
    qty = 0
    for fill in order['fills']:
        prices += (float(fill['price']) * float(fill['qty']))
        qty += float(fill['qty'])
    return prices / qty

def get_price(coin):
     return client.get_ticker(symbol=coin)['lastPrice']

def create_order(pair, usdt_to_spend, action):
    try:
        order = client.create_order(
            symbol = pair,
            side = action,
            type = 'MARKET',
            quoteOrderQty = usdt_to_spend,
            recvWindow = "10000"
        )
    except Exception as exception:       
        wrong = traceback.format_exc(limit=None, chain=True)
        sendmsg(wrong)
    return order

def executed_orders():
    global executed_queque
    while True:
        if len(executed_queque) > 0:
            if os.path.exists(executed_trades_file):
                existing_file = load_json(executed_trades_file)
                existing_file += executed_queque
            else: 
                existing_file = executed_queque
            save_json(executed_trades_file, existing_file)
            executed_queque = []
        time.sleep(0.1)
            


def schedule_Order(time_And_Pair, announcement):
    try:
        scheduled_order = {'time':time_And_Pair[0].strftime("%Y-%m-%d %H:%M:%S"), 'pairs':time_And_Pair[1]}

        sendmsg(f'[SCHEDULER] Scheduled an order for {time_And_Pair[1]} at {time_And_Pair[0]}.')
        update_json(schedules_file, scheduled_order)
        update_json(file, announcement)
    except Exception as exception:       
        wrong = traceback.format_exc(limit=None, chain=True)
        sendmsg(wrong)


def place_Order_On_Time(time_till_live, pair, threads):
    delay = 0
    global executed_queque
    try:
        if pair in current_buy_threads:
            sendmsg(f'[SCHEDULER] {pair} already on a thread.')
            return
        else:
            current_buy_threads.append(pair)

        sendmsg(f'[SCHEDULER] Thread created to buy {pair} at {time_till_live}. Sleep until then.')
        if delay_mode:
            delay = (ping_binance() * percentage)
            time_till_live = (time_till_live - timedelta(seconds = delay))

        time_to_wait = ((time_till_live - datetime.utcnow()).total_seconds() - 10)
        time.sleep(time_to_wait)
        order = {}

        if test_mode:
            price = float(get_price(pair))
            if price <= 0.00001:
                price = get_price(pair)
            while True:
                if (datetime.utcnow() - timedelta(seconds = 1) <= time_till_live <= datetime.utcnow() - timedelta(seconds = delay * 0.9)):
                    order = {
                        "symbol": pair,
                        "transactTime": datetime.timestamp(datetime.now()),
                        "price": price,
                        "origQty": ammount/float(price),
                        "executedQty": ammount/float(price),
                        "cummulativeQuoteQty": ammount,
                        "status": "FILLED",
                        "type": "MARKET",
                        "side": "BUY"
                        }
                    break
        else:
            while True:
                if (datetime.utcnow() - timedelta(seconds = 1) <= time_till_live <= datetime.utcnow() - timedelta(seconds = delay * 0.9)):
                    order = create_order(pair, ammount, 'BUY')
                    order['price'] = avFills(order)
                    break
        amount = order['executedQty']
        price = order['price']
        order['tp'] = price + (price*tp /100)
        order['sl'] = price - (price*sl /100)
        sendmsg(f'Bougth {amount} of {pair} at {price}')
        executed_queque.append(order)
    except Exception as exception:       
        wrong = traceback.format_exc(limit=None, chain=True)
        sendmsg(wrong)
######


def check_Schedules():
    try:
        if os.path.exists(schedules_file):
            unfiltered_schedules = load_json(schedules_file)
            schedules = []

            for schedule in unfiltered_schedules:

                flag = True
                datetime = dparser.parse(schedule['time'], fuzzy=True, ignoretz=True)

                if datetime < datetime.utcnow():
                    flag = False

                if flag:
                    schedules.append(schedule)

                    for pair in schedule['pairs']:
                        threading.Thread(target=place_Order_On_Time, args=(datetime, pair, threading.active_count() + 1)).start()
                        sendmsg(f'[SCHEDULER] Found scheduled order for {pair} at {datetime}. Queued.')
            save_json(schedules_file, schedules)
    except Exception as exception:       
        wrong = traceback.format_exc(limit=None, chain=True)
        sendmsg(wrong)
                

def sell():
    while True:
        try:
            flag_update = False
            not_sold_orders = []
            order = []
            if os.path.exists(executed_trades_file):
                order = load_json(executed_trades_file)
            if len(order) > 0:
                for coin in list(order):

                    # store some necesarry trade info for a sell
                    stored_price = float(coin['price'])
                    coin_tp = coin['tp']
                    coin_sl = coin['sl']
                    volume = coin['executedQty']
                    symbol = coin['symbol']

                    last_price = get_price(symbol)

                    # update stop loss and take profit values if threshold is reached
                    if float(last_price) > coin_tp and tsl_mode:
                        # increase as absolute value for TP
                        new_tp = float(last_price) + (float(last_price)*tp /100)

                        # same deal as above, only applied to trailing SL
                        new_sl = float(last_price) - (float(last_price)*sl /100)

                        # new values to be added to the json file
                        coin['tp'] = new_tp
                        coin['sl'] = new_sl
                        not_sold_orders.append(coin)
                        flag_update = True

                        threading.Thread(target=sendSpam, args=(symbol, f'[TRADING] Updated TP: {round(new_tp, 3)} and SL: {round(new_sl, 3)} for {symbol}')).start()
                    # close trade if tsl is reached or trail option is not enabled
                    elif float(last_price) < coin_sl or float(last_price) > coin_tp:
                        try:

                            # sell for real if test mode is set to false
                            if not test_mode:
                                sell = client.create_order(symbol = symbol, side = 'SELL', type = 'MARKET', quantity = volume, recvWindow = "10000")


                            sendmsg(f"[TRADING] Sold {symbol} at {(float(last_price) - stored_price) / float(stored_price)*100}.")
                            killSpam(symbol)
                            flag_update = True
                            # remove order from json file by not adding it

                        except Exception as exception:
                            wrong = traceback.format_exc(limit=None, chain=True)
                            sendmsg(wrong)

                        # store sold trades data
                        else:
                            if os.path.exists(executed_sells_file):
                                sold_coins = load_json(executed_sells_file)

                            else:
                                sold_coins = []

                            if not test_mode:
                                sold_coins.append(sell)
                            else:
                                sell = {
                                            'symbol':symbol,
                                            'price':last_price,
                                            'volume':volume,
                                            'time':datetime.timestamp(datetime.now()),
                                            'profit': float(last_price) - stored_price,
                                            'relative_profit': round((float(last_price) - stored_price) / stored_price*100, 3)
                                            }
                                sold_coins.append(sell)
                            save_json(executed_sells_file, sold_coins)
                    else:
                        not_sold_orders.append(coin)
                    if flag_update: save_json(executed_trades_file, not_sold_orders)
        except Exception as exception:       
            wrong = traceback.format_exc(limit=None, chain=True)
            sendmsg(wrong)
        time.sleep(0.2)


def parse_announcement(announcement):
    time_And_Pair = get_Pair_and_DateTime(announcement['code'])
    if time_And_Pair is not None:
        if time_And_Pair[0] >= datetime.utcnow() and len(time_And_Pair[1]) > 0:
            schedule_Order(time_And_Pair, announcement)
            for pair in time_And_Pair[1]:
                threading.Thread(target=place_Order_On_Time, args=(time_And_Pair[0], pair, threading.active_count() + 1)).start()
                sendmsg(f'[ANNOUNCEMENT] Found new announcement! Preparing schedule for: {pair}')
                existing_coins.append(re.sub( pairing, '', pair))
            save_json(coins_file, existing_coins)


def main():
    getAllExistingCoins()

    if os.path.exists(file):
        existing_Anouncements = load_json(file)
    else:
        existing_Anouncements = get_Announcements()
        for announcement in existing_Anouncements:
            parse_announcement(announcement)
        save_json(file, existing_Anouncements)

    threading.Thread(target=check_Schedules, args=()).start()
    threading.Thread(target=sell, args=()).start()
    threading.Thread(target=executed_orders, args=()).start()
    
    while True:
        new_Anouncements = get_Announcements()
        
        for announcement in new_Anouncements:
            if not announcement in existing_Anouncements:
                parse_announcement(announcement)
                existing_Anouncements = load_json(file)
        
        threading.Thread(target=sendSpam, args=("sleep", f'[[INFO]] Done checking announcements. Next check in {frequency} seconds.&disable_notification=true')).start()
        threading.Thread(target=sendSpam, args=("ping", f'[[INFO]] Current average delay: {round(ping_binance()*1000, 2)} ms.&disable_notification=true')).start()
        time.sleep(frequency)


#TODO:
# posible integration with AWS lambda ping it time before the coin is listed so it can place a limit order a little bti more than opening price
# parse breaks when there are 2 dates in a string with time. 

if __name__ == '__main__':
    try:
        if not test_mode:
            sendmsg('[[WARNING]] Running on live mode!')
        sendmsg('[[INFO]] Binance bot starting...')
        sendmsg(f'[[INFO]] Approximate delay: {round(ping_binance()*1000, 2)} ms.')
        main()
    except Exception as exception:
        wrong = traceback.format_exc(limit=None, chain=True)
        sendmsg(wrong)


