import websocket
import json
import pandas as pd
import numpy as np
import time
import requests
from datetime import datetime

# === CONFIG ===
DERIV_APP_ID = "1089"  # Use your Deriv App ID here
BOT_TOKEN = "8309380142:AAE-a5zBJVzrwcFBNwkgJvJwGSEPHV3yOsA"
CHAT_ID = "5567741626"

SYMBOLS = [
    "R_25",
    "R_25_1S",
    "R_75",
    "R_75_1S"
]

TIMEFRAME = 300  # 5 minutes in seconds
CANDLE_COUNT = 100

RSI_PERIOD = 14
STOCH_PERIOD = 14
STOCH_SIGNAL = 3
BOLL_PERIOD = 20
BOLL_STD_DEV = 2

RSI_OVERBOUGHT = 74
RSI_OVERSOLD = 26
STOCH_OVERBOUGHT = 92.5
STOCH_OVERSOLD = 7.5

# === FUNCTIONS ===

def send_telegram_message(message):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    payload = {"chat_id": CHAT_ID, "text": message}
    try:
        requests.post(url, json=payload)
    except Exception as e:
        print(f"Telegram send error: {e}")

def rsi(series, period=14):
    delta = series.diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
    rs = gain / loss
    return 100 - (100 / (1 + rs))

def stochastic_kd(df, k_period=14, d_period=3):
    low_min = df['low'].rolling(window=k_period).min()
    high_max = df['high'].rolling(window=k_period).max()
    k = 100 * (df['close'] - low_min) / (high_max - low_min)
    d = k.rolling(window=d_period).mean()
    return k, d

def bollinger_bands(series, period=20, std_dev=2):
    sma = series.rolling(window=period).mean()
    std = series.rolling(window=period).std()
    upper_band = sma + (std * std_dev)
    lower_band = sma - (std * std_dev)
    return upper_band, lower_band

def analyze(df, symbol):
    last_close = df['close'].iloc[-1]
    rsi_value = rsi(df['close'], RSI_PERIOD).iloc[-1]
    k_value, d_value = stochastic_kd(df, STOCH_PERIOD, STOCH_SIGNAL)
    stoch_k = k_value.iloc[-1]
    stoch_d = d_value.iloc[-1]
    upper_band, lower_band = bollinger_bands(df['close'], BOLL_PERIOD, BOLL_STD_DEV)
    upper_bb = upper_band.iloc[-1]
    lower_bb = lower_band.iloc[-1]

    signal = None

    # Buy condition
    if (rsi_value <= RSI_OVERSOLD) and (stoch_k <= STOCH_OVERSOLD or stoch_d <= STOCH_OVERSOLD) and (last_close <= lower_bb):
        signal = "BUY"

    # Sell condition
    elif (rsi_value >= RSI_OVERBOUGHT) and (stoch_k >= STOCH_OVERBOUGHT or stoch_d >= STOCH_OVERBOUGHT) and (last_close >= upper_bb):
        signal = "SELL"

    if signal:
        msg = (
            f"📢 Precision Vix Bot Signal\n"
            f"Symbol: {symbol}\n"
            f"Signal: {signal}\n"
            f"RSI: {rsi_value:.2f}\n"
            f"Stoch K: {stoch_k:.2f} | Stoch D: {stoch_d:.2f}\n"
            f"Close Price: {last_close:.2f}\n"
            f"Time: {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')} UTC"
        )
        send_telegram_message(msg)

def fetch_candles(symbol):
    ws = websocket.create_connection("wss://ws.binaryws.com/websockets/v3?app_id=" + DERIV_APP_ID)
    params = {
        "ticks_history": symbol,
        "adjust_start_time": 1,
        "count": CANDLE_COUNT,
        "end": "latest",
        "style": "candles",
        "granularity": TIMEFRAME
    }
    ws.send(json.dumps(params))
    data = json.loads(ws.recv())
    ws.close()

    if "candles" in data:
        candles = data["candles"]
        df = pd.DataFrame(candles)
        df['open'] = df['open'].astype(float)
        df['high'] = df['high'].astype(float)
        df['low'] = df['low'].astype(float)
        df['close'] = df['close'].astype(float)
        return df
    else:
        return None

def run_bot():
    while True:
        try:
            for symbol in SYMBOLS:
                df = fetch_candles(symbol)
                if df is not None and len(df) > RSI_PERIOD:
                    analyze(df, symbol)
            time.sleep(TIMEFRAME)
        except Exception as e:
            print(f"Error: {e}")
            time.sleep(5)

if __name__ == "__main__":
    send_telegram_message("🚀 Precision Vix Bot is now running...")
    run_bot()