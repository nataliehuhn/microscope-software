#!/usr/bin/env python

'''Using Webhook and self-signed certificate'''

# This file is an annotated example of a webhook based bot for
# telegram. It does not do anything useful, other than provide a quick
# template for whipping up a testbot. Basically, fill in the CONFIG
# section and run it.
# Dependencies (use pip to install them):
# - python-telegram-bot: https://github.com/leandrotoledo/python-telegram-bot
# - Flask              : http://flask.pocoo.org/
# Self-signed SSL certificate (make sure 'Common Name' matches your FQDN):
# $ openssl req -new -x509 -nodes -newkey rsa:1024 -keyout server.key -out server.crt -days 3650
# You can test SSL handshake running this script and trying to connect using wget:
# $ wget -O /dev/null https://$HOST:$PORT/
# Create Certificate with http://www.mobilefish.com/services/ssl_certificates/ssl_certificates.php#ssl_certificates_output

from flask import Flask, request

import telegram
import numpy as np

from scipy.misc import imsave

import sys, os
sys.path.append( os.path.join(os.path.dirname(__file__),"..") )
from CameraConnection import CameraConnection
mmc = CameraConnection()

server_path = os.path.dirname(__file__)

# CONFIG
TOKEN    = '77952384:AAFnqEzxDdlh3XMP0U3PzwZGu1Svd4npOCg'
HOST     = '131.188.117.88'#188.174.219.160' # Same FQDN used when generating SSL Cert
PORT     = 443#8443
CERT     = 'server88.crt'
CERT_KEY = 'server88.key'

bot = telegram.Bot(TOKEN)
app = Flask(__name__, static_url_path='')
context = (CERT, CERT_KEY)

@app.route('/')
def hello():
    return 'Hello World!'

@app.route('/LiveView')
def LiveView():
    return app.send_static_file('LiveView.html')
    
@app.route('/favicon.ico')
def Favicon():
    return app.send_static_file('favicon.ico')

@app.route('/status.txt')
def Status():
    return app.send_static_file('status.txt')

@app.route('/image')
def Image():
    return "blabla"#app.send_static_file('image.png')

@app.route('/' + TOKEN, methods=['POST'])
def webhook():
    update = telegram.update.Update.de_json(request.get_json(force=True))
    print update.message.text
    
    if update.message.text == "/status":
        status = ""
        with open("status.txt", 'r') as fp:
            status = fp.read().replace("<br>", "")
        bot.sendMessage(chat_id=update.message.chat_id, text=status)
        
    elif update.message.text == "/start" or update.message.text.lower() == "hallo":
        filename = os.path.join(server_path, "chats.txt")
        chat_ids = np.loadtxt(filename).astype(int).tolist()
        if type(chat_ids) == type(1):
            chat_ids = [chat_ids]
        if update.message.chat_id not in chat_ids:
            chat_ids.append(update.message.chat_id)
            np.savetxt(filename, chat_ids, "%d")
        bot.sendMessage(chat_id=update.message.chat_id, text='I will inform you about the measurements.')
        
    elif update.message.text == "/stop" or update.message.text.lower() == "shut up" or update.message.text.lower() == "halts maul" or update.message.text.lower() == "halt's maul":
        chat_ids = np.loadtxt(filename).astype(int).tolist()
        if type(chat_ids) == type(1):
            chat_ids = [chat_ids]
        if update.message.chat_id in chat_ids:
            chat_ids.remove(update.message.chat_id)
            np.savetxt(filename, chat_ids, "%d")
        bot.sendMessage(chat_id=update.message.chat_id, text='Ok, then I will shut up.')
        
    elif update.message.text == "/image":
        bot.sendChatAction(chat_id=update.message.chat_id, action=telegram.ChatAction.UPLOAD_PHOTO)
        image = mmc.getLastImage()
        filename = os.path.join(server_path, "image.png")
        imsave(filename, image)
        bot.sendPhoto(chat_id=update.message.chat_id, photo=open(filename, 'rb'))
        
    elif update.message.text == "/help":
        bot.sendMessage(chat_id=update.message.chat_id, text='Do you need help?')
        
    else:
        bot.sendMessage(chat_id=update.message.chat_id, text='I don\'t understand what you mean.')

    return 'OK'


def setWebhook():
    bot.setWebhook(webhook_url='https://%s:%s/%s' % (HOST, PORT, TOKEN),
                   certificate=open(CERT, 'rb'))

if __name__ == '__main__':
    setWebhook()

    app.run(host='0.0.0.0',
            port=PORT,
            ssl_context=context,
            debug=True)
