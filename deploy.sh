#!/bin/bash
cd /home/user/trading_bot
git pull origin main
pip install -r requirements.txt
sudo systemctl restart trading-bot.service