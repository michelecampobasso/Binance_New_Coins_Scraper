import os
import re
import time
import json
import requests
import threading
from utils.json_manage import *
from utils.binance_key import *
from utils.config import *
from datetime import datetime, timedelta
import dateutil.parser as dparser


telegram_keys= []
pair_Dict = {}

telegram_status = False
if os.path.exists('conf/telegram.yml'):
    telegram_keys = load_config('conf/telegram.yml')
    telegram_status = True



def sendmsg(message):
    print(message)
    threading.Thread(target=telegram_bot_sendtext, args=(message,)).start()

def telegram_bot_sendtext(bot_message):
    send_text = 'https://api.telegram.org/bot' + str(telegram_keys['telegram_key']) + '/sendMessage?chat_id=' + str(telegram_keys['chat_id']) + '&parse_mode=Markdown&text=' + bot_message
    response = requests.get(send_text)
    return response.json()['result']['message_id']

def telegram_delete_message(message_id):
    send_text = 'https://api.telegram.org/bot' + str(telegram_keys['telegram_key']) + '/deleteMessage?chat_id=' + str(telegram_keys['chat_id']) + '&message_id=' + str(message_id)
    requests.get(send_text)


class Send_Without_Spamming():
    def __init__(self):
        self.id = 0000
        self.first = True
    
    def send(self, message):
        if telegram_status:
            if self.first:
                self.first = False
                self.id = telegram_bot_sendtext(message)
            else:
                telegram_delete_message(self.id)
                self.id = telegram_bot_sendtext(message)
        else:
            print(message)
        
    def kill(self, pair):
        if telegram_status:
            telegram_delete_message(self.id)
            del pair_Dict[pair] 

def killSpam(pair):
    if telegram_status:
        try:
            pair_Dict[pair].kill(pair)
        except Exception:
            pass
            
def sendSpam(pair, message):
    if telegram_status:
        try:
            pair_Dict[pair].send(message)
        except Exception:
            pair_Dict[pair] = Send_Without_Spamming()
            pair_Dict[pair].send(message)

