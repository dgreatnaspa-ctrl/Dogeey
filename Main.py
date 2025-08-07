import os
import time
import logging
import requests
import numpy as np
from datetime import datetime, timedelta

# Environment setup
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

SYMBOLS = [
    "R_10", "R_10_1s", "R_25", "R_25_1s", "R_50",
    "R_50_1s", "R_75", "R_75_1s", "R_100", "R_100_1s"
]

logging.basicConfig(level=logging.INFO)

def send_telegram_message(message):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    data = {"chat_id": TELEGRAM_CHAT_ID, "text": message}
    try:
        r = requests.post(url, data=data)
        if r.status_code != 200:
            logging.error(f"Telegram Error: {r.text}")
    except Exception as e:
        logging.error(f"Telegram send error: {e}")

def fetch_candles(symbol, count=100):
    url = "https://api.deriv.com/api/websockets/v3"
    response = requests.get(
        f"https://api.deriv.com/api/exchange/v1/price?index={symbol}&interval=5m&count={count}"
    )
    try:
        data = response.json()
        candles = data["candles"]
        return candles
    except:
        logging.error(f"Failed to fetch data for {symbol}")
        return []

def calculate_indicators(candles):
    closes = np.array([c["close"] for c in candles])

    # Bollinger Bands
    period = 20
    sma = np.convolve(closes, np.ones(period)/period, mode='valid')
    std = np.std(closes[-period:])
    upper_band = sma[-1] + 2 * std
    lower_band = sma[-1] - 2 * std
    last_close = closes[-1]

    # RSI
    delta = np.diff(closes)
    up = np.where(delta > 0, delta, 0)
    down = np.where(delta < 0, -delta, 0)
    avg_gain = np.mean(up[-14:])
    avg_loss = np.mean(down[-14:])
    rs = avg_gain / avg_loss if avg_loss != 0 else 0
    rsi = 100 - (100 / (1 + rs))

    # Stochastic Oscillator
    k_period = 14
    lows = np.array([c["low"] for c in candles])
    highs = np.array([c["high"] for c in candles])
    low_min = np.min(lows[-k_period:])
    high_max = np.max(highs[-k_period:])
    stoch_k = 100 * ((closes[-1] - low_min) / (high_max - low_min)) if high_max != low_min else 0
    stoch_d = np.mean([stoch_k for _ in range(3)])  # Simple smoothing

    return {
        "last_close": last_close,
        "upper_band": upper_band,
        "lower_band": lower_band,
        "rsi": rsi,
        "stoch_k": stoch_k,
        "stoch_d": stoch_d
    }

def validate_buy_condition(prev_rsi, rsi, stoch_k, stoch_d, prev_k, prev_d, price, lower_band):
    return (
        price < lower_band and
        prev_rsi < 26 and rsi > 26 and
        prev_k < prev_d and stoch_k > stoch_d and
        prev_k < 7.5 and stoch_k > 7.5
    )

def validate_sell_condition(prev_rsi, rsi, stoch_k, stoch_d, prev_k, prev_d, price, upper_band):
    return (
        price > upper_band and
        prev_rsi > 74 and rsi < 74 and
        prev_k > prev_d and stoch_k < stoch_d and
        prev_k > 92.5 and stoch_k < 92.5
    )

def check_strategy(symbol):
    candles = fetch_candles(symbol, count=100)
    if len(candles) < 21:
        logging.warning(f"Not enough candles for {symbol}")
        return

    indicators = calculate_indicators(candles)
    prev = calculate_indicators(candles[:-1])  # previous candle

    # Unpack
    price = indicators["last_close"]
    upper_band = indicators["upper_band"]
    lower_band = indicators["lower_band"]
    rsi = indicators["rsi"]
    prev_rsi = prev["rsi"]
    stoch_k = indicators["stoch_k"]
    stoch_d = indicators["stoch_d"]
    prev_k = prev["stoch_k"]
    prev_d = prev["stoch_d"]

    # Conditions
    if validate_buy_condition(prev_rsi, rsi, stoch_k, stoch_d, prev_k, prev_d, price, lower_band):
        message = (
            f"🟢 *BUY Signal* — {symbol}\n\n"
            f"📉 Price: {price:.2f}\n"
            f"📊 RSI: {rsi:.2f} (prev: {prev_rsi:.2f})\n"
            f"🌀 Stochastic: K={stoch_k:.2f}, D={stoch_d:.2f}\n"
            f"📍 BB Lower Band: {lower_band:.2f}\n"
            f"⏰ Entry in 2 minutes!"
        )
        send_telegram_message(message)

    elif validate_sell_condition(prev_rsi, rsi, stoch_k, stoch_d, prev_k, prev_d, price, upper_band):
        message = (
            f"🔴 *SELL Signal* — {symbol}\n\n"
            f"📈 Price: {price:.2f}\n"
            f"📊 RSI: {rsi:.2f} (prev: {prev_rsi:.2f})\n"
            f"🌀 Stochastic: K={stoch_k:.2f}, D={stoch_d:.2f}\n"
            f"📍 BB Upper Band: {upper_band:.2f}\n"
            f"⏰ Entry in 2 minutes!"
        )
        send_telegram_message(message)

def main():
    while True:
        logging.info("🔄 Scanning for signals...")
        for symbol in SYMBOLS:
            check_strategy(symbol)
        time.sleep(300)  # Run every 5 minutes

if __name__ == "__main__":
    main()
