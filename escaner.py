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
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": mensaje, "parse_mode": "HTML"}
    try:
        r = requests.post(url, json=payload, timeout=10)
        if r.status_code != 200:
            requests.post(url, json={"chat_id": TELEGRAM_CHAT_ID, "text": mensaje}, timeout=10)
    except Exception as e:
        print(f"Error Telegram: {e}")

def obtener_top_monedas(limite=50):
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
    except Exception:
        pass
    return ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT", "ADAUSDT", "DOGEUSDT", "AVAXUSDT", "LINKUSDT", "SUIUSDT", "DOTUSDT", "NEARUSDT", "LTCUSDT", "UNIUSDT", "APTUSDT"]

def calcular_rsi(series, period=14):
    delta = series.diff()
    gain = (delta.where(delta > 0, 0)).ewm(alpha=1/period, adjust=False).mean()
    loss = (-delta.where(delta < 0, 0)).ewm(alpha=1/period, adjust=False).mean()
    rs = gain / loss
    return 100 - (100 / (1 + rs))

def calcular_supertrend(df, period=10, multiplier=3.0):
    high, low, close = df['high'], df['low'], df['close']
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

def detectar_soportes_resistencias(df):
    """Detecta pisos (soportes) y techos (resistencias) historicos con pivotes de 5 dias"""
    soportes = []
    resistencias = []
    # Analizamos hasta hace 3 dias para tener pivotes confirmados
    for i in range(5, len(df) - 3):
        es_piso = df['low'].iloc[i] == df['low'].iloc[i-5:i+4].min()
        es_techo = df['high'].iloc[i] == df['high'].iloc[i-5:i+4].max()
        if es_piso:
            soportes.append(df['low'].iloc[i])
        if es_techo:
            resistencias.append(df['high'].iloc[i])
    return soportes, resistencias

def escanear():
    monedas = obtener_top_monedas(50)
    alertas = []

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
            rsi = hoy['RSI']

            # Filtro base de seguridad para todas: que no este en desplome libre (RSI >= 34) y muestre freno/reaccion
            vela_freno = (precio >= hoy['open']) or ((precio - hoy['low']) > (hoy['high'] - hoy['low']) * 0.4)
            if rsi < 34 or not vela_freno:
                continue

            motivos = []

            # MOTOR 1: Rebote en SuperTrend Verde (Independiente)
            distancia_st = (precio - hoy['SuperTrend']) / hoy['SuperTrend']
            if hoy['ST_Trend'] == 1 and (0 <= distancia_st <= 0.03) and rsi <= 62:
                motivos.append(f"🟩 Apoyo SuperTrend (${hoy['SuperTrend']:.4f})")

            # MOTOR 2: Retroceso Fibonacci 61.8% - 71.3% (Independiente)
            ventana = df.iloc[-60:]
            max_impulso = ventana['high'].max()
            idx_max = ventana['high'].idxmax()
            ventana_previa = df.loc[:idx_max].tail(45)
            min_impulso = ventana_previa['low'].min()
            rango = max_impulso - min_impulso

            fib_786 = precio * 0.95
            if rango > 0 and precio < max_impulso:
                fib_618 = max_impulso - (rango * 0.618)
                fib_713 = max_impulso - (rango * 0.713)
                fib_786 = max_impulso - (rango * 0.786)
                if (fib_786 <= precio <= fib_618 * 1.01) or (fib_713 <= hoy['low'] <= fib_618):
                    motivos.append(f"🎯 Zona Fibonacci 61.8-71.3% (${fib_618:.4f})")

            # MOTOR 3: Soportes y Resistencias (Independiente)
            soportes, resistencias = detectar_soportes_resistencias(df.iloc[-65:])
            soporte_cercano = None
            for s in reversed(soportes):
                # Si el precio actual esta apoyado a menos de 1.8% por encima de un piso historico
                if 0 <= (precio - s) / s <= 0.018:
                    soporte_cercano = s
                    motivos.append(f"🧱 Rebote en Soporte Clave (${s:.4f})")
                    break

            # Tambien revisa Retesteo (Antiguo techo roto que ahora funciona como piso)
            if not soporte_cercano:
                for res in reversed(resistencias):
                    if 0 <= (precio - res) / res <= 0.018 and df['close'].iloc[-5:-1].max() > res:
                        soporte_cercano = res
                        motivos.append(f"🔄 Retesteo de Techo Roto (${res:.4f})")
                        break

            # Si cumplio AL MENOS UNO de los 3 motores independientes, dispara la señal
            if motivos:
                atr = hoy['ATR']
                stop_loss = precio - (1.5 * atr)
                
                # Busca el proximo techo (resistencia) por encima del precio actual
                techos_arriba = [r for r in resistencias if r > precio * 1.03]
                techo_ref = min(techos_arriba) if techos_arriba else (precio + (atr * 3.0))

                riesgo = precio - stop_loss
                tp1 = precio + (riesgo * 2.0)
                tp2 = max(techo_ref, precio + (riesgo * 3.0))

                pct_sl = ((stop_loss - precio) / precio) * 100
                pct_tp1 = ((tp1 - precio) / precio) * 100
                pct_tp2 = ((tp2 - precio) / precio) * 100

                etiqueta = "🔥 <b>CONFLUENCIA MULTIPLE</b>" if len(motivos) > 1 else "🟢 <b>SEÑAL SPOT 1D</b>"

                alertas.append(
                    f"{etiqueta}: <b>{symbol}</b>\n"
                    f"🔹 <b>Precio Real:</b> ${precio:.4f}\n"
                    f"📊 <b>Motor:</b> {' + '.join(motivos)}\n"
                    f"📈 <b>RSI (1D):</b> {rsi:.1f}\n"
                    f"🏛 <b>Próximo Techo (Resistencia):</b> ${techo_ref:.4f}\n"
                    f"🛑 <b>Stop Loss:</b> ${stop_loss:.4f} ({pct_sl:.1f}%)\n"
                    f"🎯 <b>Take Profit 1:</b> ${tp1:.4f} (+{pct_tp1:.1f}%)\n"
                    f"🎯 <b>Take Profit 2:</b> ${tp2:.4f} (+{pct_tp2:.1f}%)"
                )
        except Exception:
            continue

    if alertas:
        # Enviamos las mejores (maximo 10 por mensaje para no saturar)
        encabezado = f"🚀 <b>ESCANEO EN VIVO BINANCE (1D)</b>\nMonedas que cumplen hoy ({len(alertas)}):\n━━━━━━━━━━━━━━━━━━\n\n"
        enviar_telegram(encabezado + "\n\n━━━━━━━━━━━━━━━━━━\n\n".join(alertas[:10]))
    else:
        enviar_telegram("🔎 Escaneo 1D completado: Ninguna de las 50 monedas principales está apoyada en SuperTrend, Fibonacci o Soporte en este instante.")

if __name__ == "__main__":
    escanear()
