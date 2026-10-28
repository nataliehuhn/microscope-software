# -*- coding: utf-8 -*-
"""
Created on Thu Sep 17 10:33:53 2015

@author: Mikroskop
"""
import os
import telegram
import numpy as np

def SendBotMessage(message_text = "Hey your measruement is finished"):
    # CONFIG
    config = dict()
    execfile("Server_Config.txt", globals(), config)
    bot = telegram.Bot(config["TOKEN"])
    
    chat_ids = np.loadtxt("chats.txt").astype(int).tolist()
    if type(chat_ids) == type(1):
        chat_ids = [chat_ids]
    for chat_id in chat_ids:
        bot.sendMessage(chat_id=chat_id, text=message_text)
