import os
import requests
import pandas as pd
import numpy as np

TELEGRAM_TOKEN = (os.environ.get("TELEGRAM_TOKEN") or "").strip()
TELEGRAM_CHAT_ID = (os.environ.get("TELEGRAM_CHAT_ID") or "").strip()
EVENT_NAME = os.environ.get("GITHUB_EVENT_NAME", "manual")

BASE_URL = "https://data-api.binance.vision/api/v3"

def enviar_telegram(mensaje):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    # Usamos HTML en lugar de Markdown para que Telegram nunca bloquee el mensaje por simbolos
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": mensaje, "parse_mode": "HTML"}
    try:
        r = requests.post(url, json=payload, timeout=10)
        print(f"Estado Telegram: {r.status_code} | Respuesta: {r.text}")
        if r.status_code != 200:
            # Si falla por formato, lo envia en texto plano sin formato
            requests.post(url, json={"chat_id": TELEGRAM_CHAT_ID, "text": mensaje}, timeout=10)
    except Exception as e:
        print(f"Error de conexion con Telegram: {e}")

def obtener_top_monedas(limite=40):
    excluir = ['USDCUSDT', 'FDUSDUSDT', 'TUSDUSDT', 'USDPUSDT', 'DAIUSDT', 'EURUSDT', 'PAXGUSDT']
    try:
        r = requests.get(f"{BASE_URL}/ticker/24hr", timeout=10)
        if r.status_code == 200:
            datos = r.json()
            pares_usdt = [
                d for d in datos 
                if d['symbol'].endswith('USDT') 
                and d['symbol'] not in excluir
                and not any(x in d['symbol'] for x in ['UPUSDT', 'DOWNUSDT', 'BULL', 'BEAR'])
            ]
            pares_ordenados = sorted(pares_usdt, key=lambda x: float(x['quoteVolume']), reverse=True)
            return [p['symbol'] for p in pares_ordenados[:limite]]
    except Exception as e:
        print(f"Usando lista base por error en API: {e}")
    return ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT", "ADAUSDT", "DOGEUSDT", "AVAXUSDT", "LINKUSDT", "SUIUSDT", "DOTUSDT", "NEARUSDT", "LTCUSDT", "UNIUSDT", "APTUSDT"]

def calcular_rsi(series, period=14):
    delta = series.diff()
    gain = (delta.where(delta > 0, 0)).ewm(alpha=1/period, adjust=False).mean()
    loss = (-delta.where(delta < 0, 0)).ewm(alpha=1/period, adjust=False).mean()
    rs = gain / loss
    return 100 - (100 / (1 + rs))

def calcular_supertrend(df, period=10, multiplier=3.0):
    high = df['high']
    low = df['low']
    close = df['close']
    
    tr1 = high - low
    tr2 = (high - close.shift(1)).abs()
    tr3 = (low - close.shift(1)).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    atr = tr.ewm(alpha=1/period, adjust=False).mean()
    
    hl2 = (high + low) / 2
    upperband = (hl2 + (multiplier * atr)).values
    lowerband = (hl2 - (multiplier * atr)).values
    close_vals = close.values
    
    st = np.zeros(len(df))
    trend = np.ones(len(df))
    
    for i in range(1, len(df)):
        if close_vals[i-1] > upperband[i-1]:
            trend[i] = 1
        elif close_vals[i-1] < lowerband[i-1]:
            trend[i] = -1
        else:
            trend[i] = trend[i-1]
            if trend[i] == 1 and lowerband[i] < lowerband[i-1]:
                lowerband[i] = lowerband[i-1]
            if trend[i] == -1 and upperband[i] > upperband[i-1]:
                upperband[i] = upperband[i-1]
                
        st[i] = lowerband[i] if trend[i] == 1 else upperband[i]
        
    df['ATR'] = atr
    df['SuperTrend'] = st
    df['ST_Trend'] = trend
    return df

def ya_alerto_hoy(symbol):
    try:
        r = requests.get(f"{BASE_URL}/klines", params={"symbol": symbol, "interval": "4h", "limit": 3}, timeout=5)
        velas_4h = r.json()
        min_anterior = float(velas_4h[-3][3])
        min_reciente = min(float(velas_4h[-2][3]), float(velas_4h[-1][3]))
        return min_anterior <= min_reciente * 1.005
    except Exception:
        return False

def escanear():
    monedas = obtener_top_monedas(40)
    alertas = []
    resumen_btc = "No disponible"

    for symbol in monedas:
        try:
            r = requests.get(f"{BASE_URL}/klines", params={"symbol": symbol, "interval": "1d", "limit": 100}, timeout=10)
            if r.status_code != 200:
                continue
                
            df = pd.DataFrame(r.json(), columns=[
                'time', 'open', 'high', 'low', 'close', 'vol', 
                'close_time', 'qav', 'num_trades', 'taker_base', 'taker_quote', 'ignore'
            ])
            for col in ['open', 'high', 'low', 'close', 'vol']:
                df[col] = df[col].astype(float)

            df = calcular_supertrend(df, period=10, multiplier=3.0)
            df['RSI'] = calcular_rsi(df['close'], 14)
            df['Vol_SMA20'] = df['vol'].rolling(20).mean()

            hoy = df.iloc[-1]
            ayer = df.iloc[-2]
            precio = hoy['close']

            if symbol == "BTCUSDT":
                estado_st = "🟩 Alcista" if hoy['ST_Trend'] == 1 else "🟥 Bajista"
                resumen_btc = f"• <b>BTCUSDT:</b> ${precio:.2f} | RSI 1D: {hoy['RSI']:.1f} | SuperTrend: {estado_st}"

            if hoy['ST_Trend'] != 1:
                continue

            ventana = df.iloc[-60:]
            max_impulso = ventana['high'].max()
            idx_max = ventana['high'].idxmax()
            ventana_previa = df.loc[:idx_max].tail(45)
            min_impulso = ventana_previa['low'].min()
            rango = max_impulso - min_impulso

            if rango <= 0 or precio >= max_impulso:
                continue

            fib_618 = max_impulso - (rango * 0.618)
            fib_713 = max_impulso - (rango * 0.713)
            fib_786 = max_impulso - (rango * 0.786)

            en_fibonacci = (fib_786 <= precio <= fib_618 * 1.015) or (fib_713 <= hoy['low'] <= fib_618)
            distancia_st = (precio - hoy['SuperTrend']) / hoy['SuperTrend']
            rebote_supertrend = (0 <= distancia_st <= 0.025)

            rsi_sano = 32 <= hoy['RSI'] <= 60
            vela_reaccion = (precio > hoy['open']) or (ayer['vol'] > ayer['Vol_SMA20'] * 1.2)

            if (en_fibonacci or rebote_supertrend) and rsi_sano and vela_reaccion:
                if EVENT_NAME == "schedule" and ya_alerto_hoy(symbol) and ayer['low'] <= fib_618:
                    continue

                atr = hoy['ATR']
                stop_loss = min(hoy['SuperTrend'], fib_786) - (0.5 * atr)
                riesgo = precio - stop_loss
                if riesgo <= 0:
                    stop_loss = precio - (1.5 * atr)
                    riesgo = precio - stop_loss

                tp1 = precio + (riesgo * 2.0)
                tp2 = precio + (riesgo * 3.0)
                pct_sl = ((stop_loss - precio) / precio) * 100
                pct_tp1 = ((tp1 - precio) / precio) * 100
                pct_tp2 = ((tp2 - precio) / precio) * 100

                motivos = []
                if en_fibonacci:
                    motivos.append("🎯 Zona Fibonacci (61.8% - 71.3%)")
                if rebote_supertrend:
                    motivos.append("🟩 Apoyo en SuperTrend Diario")

                alertas.append(
                    f"🟢 <b>SEÑAL SPOT 1D: {symbol}</b>\n"
                    f"🔹 <b>Entrada:</b> ${precio:.4f}\n"
                    f"📊 <b>Confluencia:</b> {' + '.join(motivos)}\n"
                    f"📈 <b>RSI (1D):</b> {hoy['RSI']:.1f} | <b>SuperTrend:</b> ${hoy['SuperTrend']:.4f}\n"
                    f"🛡 <b>Gestión de Riesgo:</b>\n"
                    f"🛑 Stop Loss: ${stop_loss:.4f} ({pct_sl:.1f}%)\n"
                    f"🎯 Take Profit 1: ${tp1:.4f} (+{pct_tp1:.1f}%)\n"
                    f"🎯 Take Profit 2: ${tp2:.4f} (+{pct_tp2:.1f}%)"
                )
        except Exception as e:
            print(f"Error analizando {symbol}: {e}")
            continue

    if alertas:
        encabezado = "🚀 <b>OPORTUNIDADES SPOT (VELAS DIARIAS 1D)</b>\n━━━━━━━━━━━━━━━━━━\n\n"
        enviar_telegram(encabezado + "\n\n━━━━━━━━━━━━━━━━━━\n\n".join(alertas))
    elif EVENT_NAME != "schedule":
        enviar_telegram(
            f"✅ <b>Escáner Spot 1D Activo (Prueba Manual)</b>\n\n"
            f"Se analizaron las {len(monedas)} monedas con más volumen de Binance.\n"
            f"En este momento ninguna cumple todos los filtros estrictos (SuperTrend Verde + Fibonacci 61.8-71.3%).\n\n"
            f"📊 <b>Referencia del mercado hoy:</b>\n{resumen_btc}"
        )

if __name__ == "__main__":
    escanear()
