import os
import requests
import pandas as pd

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

MONEDAS = [
    "BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT",
    "ADAUSDT", "DOGEUSDT", "AVAXUSDT", "LINKUSDT", "DOTUSDT",
    "NEARUSDT", "LTCUSDT", "UNIUSDT", "APTUSDT", "SUIUSDT"
]

def enviar_telegram(mensaje):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": mensaje, "parse_mode": "Markdown"}
    requests.post(url, json=payload)

def calcular_rsi(series, period=14):
    delta = series.diff()
    gain = (delta.where(delta > 0, 0)).ewm(alpha=1/period, adjust=False).mean()
    loss = (-delta.where(delta < 0, 0)).ewm(alpha=1/period, adjust=False).mean()
    rs = gain / loss
    return 100 - (100 / (1 + rs))

def escanear():
    alertas = []
    base_url = "https://data-api.binance.vision/api/v3/klines"

    for symbol in MONEDAS:
        params = {"symbol": symbol, "interval": "1h", "limit": 50}
        r = requests.get(base_url, params=params)
        if r.status_code != 200:
            continue
            
        data = r.json()
        df = pd.DataFrame(data, columns=[
            'time', 'open', 'high', 'low', 'close', 'vol', 
            'close_time', 'qav', 'num_trades', 'taker_base', 'taker_quote', 'ignore'
        ])
        df['close'] = df['close'].astype(float)
        
        df['EMA20'] = df['close'].ewm(span=20, adjust=False).mean()
        df['RSI'] = calcular_rsi(df['close'], 14)

        vela_actual = df.iloc[-2]
        vela_previa = df.iloc[-3]

        precio = vela_actual['close']
        rsi = vela_actual['RSI']
        ema20 = vela_actual['EMA20']

        cruce_ema = (vela_previa['close'] < vela_previa['EMA20']) and (precio > ema20)

        if rsi < 35 or cruce_ema:
            motivo = "RSI menor a 35 (Sobreventa)" if rsi < 35 else "Cruce alcista sobre EMA 20"
            alertas.append(
                f"🟢 *{symbol}* (1H)\n"
                f"• Motivo: {motivo}\n"
                f"• Precio: `${precio:.4f}`\n"
                f"• RSI: `{rsi:.1f}` | EMA20: `${ema20:.4f}`"
            )

    if alertas:
        mensaje_final = "🚀 *ALERTAS BINANCE (1H)*\n\n" + "\n\n".join(alertas)
        enviar_telegram(mensaje_final)
    else:
        enviar_telegram("🔎 Escaneo 1H completado: Ninguna moneda cumplió la condición en esta vela.")

if __name__ == "__main__":
    escanear()
