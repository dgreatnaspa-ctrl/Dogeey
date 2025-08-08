import os
import time
import json
import logging
from datetime import datetime
from dotenv import load_dotenv

import websocket
import pandas as pd
import numpy as np
import requests

load_dotenv()

# ---------- CONFIG (from env) ----------
DERIV_WS_URL = os.getenv("DERIV_WS_URL", "wss://ws.binaryws.com/websockets/v3")
DERIV_APP_ID = os.getenv("DERIV_APP_ID", "")  # optional
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")
SYMBOLS = [s.strip() for s in os.getenv("SYMBOLS", "R_50,R_75,R_100,R_25").split(",") if s.strip()]

TIMEFRAME = int(os.getenv("TIMEFRAME", "300"))  # 5 minutes in seconds
CANDLE_COUNT = int(os.getenv("CANDLE_COUNT", "200"))

RSI_PERIOD = int(os.getenv("RSI_PERIOD", "14"))
STOCH_K_PERIOD = int(os.getenv("STOCH_K_PERIOD", "14"))
STOCH_D_PERIOD = int(os.getenv("STOCH_D_PERIOD", "3"))
BOLL_PERIOD = int(os.getenv("BOLL_PERIOD", "20"))
BOLL_STD = float(os.getenv("BOLL_STD", "2"))

RSI_OVERBOUGHT = float(os.getenv("RSI_OVERBOUGHT", "74"))
RSI_OVERSOLD = float(os.getenv("RSI_OVERSOLD", "26"))
STOCH_OVERBOUGHT = float(os.getenv("STOCH_OVERBOUGHT", "92.5"))
STOCH_OVERSOLD = float(os.getenv("STOCH_OVERSOLD", "7.5"))

CHECK_INTERVAL = TIMEFRAME  # run every candle

# ---------- Logging ----------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)

# ---------- Utilities ----------
def send_telegram_message(text: str):
    if not BOT_TOKEN or not CHAT_ID:
        logging.warning("Telegram token/chat not set - skipping send.")
        return
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    payload = {"chat_id": CHAT_ID, "text": text, "parse_mode": "Markdown"}
    try:
        r = requests.post(url, json=payload, timeout=10)
        if r.status_code != 200:
            logging.warning("Telegram send failed: %s", r.text)
    except Exception as e:
        logging.error("Telegram exception: %s", e)

def fetch_candles(symbol: str, count: int = CANDLE_COUNT, granularity: int = TIMEFRAME):
    """
    Request ticks_history (candles) from Deriv via ephemeral websocket connection.
    Returns pandas.DataFrame or None.
    """
    # build ws url with app_id if provided
    ws_url = DERIV_WS_URL
    if DERIV_APP_ID:
        if "?" in ws_url:
            ws_url = ws_url + "&app_id=" + DERIV_APP_ID
        else:
            ws_url = ws_url + "?app_id=" + DERIV_APP_ID

    payload = {
        "ticks_history": symbol,
        "style": "candles",
        "granularity": granularity,
        "count": count,
        "end": "latest",
        "subscribe": 0
    }
    try:
        ws = websocket.create_connection(ws_url, timeout=8)
        ws.send(json.dumps(payload))
        raw = ws.recv()
        ws.close()
        data = json.loads(raw)
    except Exception as e:
        logging.warning("Fetch candles error for %s: %s", symbol, e)
        return None

    if not data or 'history' not in data or 'candles' not in data['history']:
        logging.debug("No candles returned for %s: %s", symbol, data)
        return None

    candles = data['history']['candles']
    df = pd.DataFrame(candles)
    # ensure numeric types
    for c in ['open', 'high', 'low', 'close']:
        df[c] = df[c].astype(float)
    df['epoch'] = pd.to_datetime(df['epoch'], unit='s')
    df.set_index('epoch', inplace=True)
    return df

# ---------- Indicators ----------
def compute_rsi(series: pd.Series, period: int = RSI_PERIOD):
    delta = series.diff()
    up = delta.clip(lower=0)
    down = -1 * delta.clip(upper=0)
    ma_up = up.ewm(alpha=1/period, adjust=False).mean()
    ma_down = down.ewm(alpha=1/period, adjust=False).mean()
    rs = ma_up / (ma_down + 1e-12)
    return 100 - (100 / (1 + rs))

def compute_stochastic(df: pd.DataFrame, k_period: int = STOCH_K_PERIOD, d_period: int = STOCH_D_PERIOD):
    low_min = df['low'].rolling(window=k_period, min_periods=1).min()
    high_max = df['high'].rolling(window=k_period, min_periods=1).max()
    k = 100 * (df['close'] - low_min) / (high_max - low_min + 1e-12)
    d = k.rolling(window=d_period, min_periods=1).mean()
    return k, d

def compute_bbands(series: pd.Series, period: int = BOLL_PERIOD, nstd: float = BOLL_STD):
    ma = series.rolling(window=period, min_periods=1).mean()
    std = series.rolling(window=period, min_periods=1).std().fillna(0)
    upper = ma + nstd * std
    lower = ma - nstd * std
    return upper, ma, lower

# ---------- Strategy / Decision ----------
last_sent = {}  # {symbol: {"signal": str, "ts": epoch}}

def analyze_symbol(symbol: str):
    df = fetch_candles(symbol)
    if df is None or len(df) < max(BOLL_PERIOD, RSI_PERIOD, STOCH_K_PERIOD) + 1:
        logging.info("[%s] not enough data", symbol)
        return

    # compute indicators
    df = df.copy()
    df['rsi'] = compute_rsi(df['close'], RSI_PERIOD)
    k, d = compute_stochastic(df, STOCH_K_PERIOD, STOCH_D_PERIOD)
    df['stoch_k'] = k
    df['stoch_d'] = d
    upper, mid, lower = compute_bbands(df['close'], BOLL_PERIOD, BOLL_STD)
    df['bb_upper'] = upper
    df['bb_mid'] = mid
    df['bb_lower'] = lower

    last = df.iloc[-1]
    prev = df.iloc[-2] if len(df) >= 2 else last

    rsi_val = float(last['rsi'])
    stoch_k = float(last['stoch_k'])
    stoch_d = float(last['stoch_d'])
    close = float(last['close'])
    upper_bb = float(last['bb_upper'])
    lower_bb = float(last['bb_lower'])

    # Check stochastic touch (no crossover required)
    touch_overb = (stoch_k >= STOCH_OVERBOUGHT) or (stoch_d >= STOCH_OVERBOUGHT)
    touch_overs = (stoch_k <= STOCH_OVERSOLD) or (stoch_d <= STOCH_OVERSOLD)

    signal = None
    reason = []

    # SELL: price >= upper BB, RSI >= overbought, stochastic touches overbought
    if touch_overb and (rsi_val >= RSI_OVERBOUGHT) and (close >= upper_bb):
        signal = "SELL"
        reason = f"Stoch_touch(OB) + RSI {rsi_val:.2f} >= {RSI_OVERBOUGHT} + close >= upper_BB"

    # BUY: price <= lower BB, RSI <= oversold, stochastic touches oversold
    elif touch_overs and (rsi_val <= RSI_OVERSOLD) and (close <= lower_bb):
        signal = "BUY"
        reason = f"Stoch_touch(OS) + RSI {rsi_val:.2f} <= {RSI_OVERSOLD} + close <= lower_BB"

    # Optionally: you can add weaker signals if you want more freq (commented)
    # elif touch_overs and rsi_val <= (RSI_OVERSOLD + 5):
    #     signal = "WEAK BUY"
    # ... etc.

    if signal:
        prev_sig = last_sent.get(symbol, {}).get("signal")
        # send if changed (or not sent before)
        if prev_sig != signal:
            msg = build_message(symbol, signal, rsi_val, stoch_k, stoch_d, close, upper_bb, lower_bb, reason)
            send_telegram_message(msg)
            last_sent[symbol] = {"signal": signal, "ts": time.time()}
            logging.info("[%s] Sent %s | %s", symbol, signal, reason)
        else:
            logging.debug("[%s] Same signal (%s) - not resending", symbol, signal)
    else:
        logging.debug("[%s] No valid signal. rsi=%.2f stoch_k=%.2f stoch_d=%.2f close=%.5f", symbol, rsi_val, stoch_k, stoch_d, close)

def build_message(symbol, signal, rsi_val, stoch_k, stoch_d, close, upper_bb, lower_bb, reason):
    t = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
    msg = (
        f"📊 *Precision Vix Bot*\n"
        f"*Symbol:* `{symbol}`\n"
        f"*Signal:* *{signal}*\n"
        f"*Time (UTC):* `{t}`\n"
        f"*Reason:* {reason}\n\n"
        f"*Indicators:*\n"
        f"• RSI: `{rsi_val:.2f}`\n"
        f"• Stoch K/D: `{stoch_k:.2f}` / `{stoch_d:.2f}`\n"
        f"• Close: `{close:.5f}`\n"
        f"• BB Upper: `{upper_bb:.5f}`  BB Lower: `{lower_bb:.5f}`\n\n"
        f"_Action:_ Enter at next 5m candle open. Suggested expiry: *10m*"
    )
    return msg

# ---------- Runner ----------
def run_loop():
    logging.info("Starting Precision Vix Bot for symbols: %s", SYMBOLS)
    # send one start message
    send_telegram_message("🚀 Precision Vix Bot (5m) is now running.")
    while True:
        try:
            for sym in SYMBOLS:
                try:
                    analyze_symbol(sym)
                except Exception as e:
                    logging.exception("Error analyzing %s: %s", sym, e)
            time.sleep(CHECK_INTERVAL)
        except KeyboardInterrupt:
            logging.info("Stopped by user")
            break
        except Exception as e:
            logging.exception("Main loop error: %s", e)
            time.sleep(5)

if __name__ == "__main__":
    run_loop()