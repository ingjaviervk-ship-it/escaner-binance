import os
import requests
import pandas as pd
import numpy as np

TELEGRAM_TOKEN = (os.environ.get("TELEGRAM_TOKEN") or "").strip()
TELEGRAM_CHAT_ID = (os.environ.get("TELEGRAM_CHAT_ID") or "").strip()

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

def obtener_top_monedas(limite=60):
    excluir = [
        'USDCUSDT', 'FDUSDUSDT', 'TUSDUSDT', 'USDPUSDT', 'DAIUSDT', 
        'EURUSDT', 'PAXGUSDT', 'USD1USDT', 'USDEUSDT', 'BUSDUSDT'
    ]
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
    """Detecta pisos (soportes) y techos (resistencias) con ventana de 3 dias a cada lado"""
    soportes = []
    resistencias = []
    for i in range(3, len(df) - 2):
        es_piso = df['low'].iloc[i] == df['low'].iloc[i-3:i+3].min()
        es_techo = df['high'].iloc[i] == df['high'].iloc[i-3:i+3].max()
        if es_piso:
            soportes.append(df['low'].iloc[i])
        if es_techo:
            resistencias.append(df['high'].iloc[i])
    return soportes, resistencias

def escanear():
    monedas = obtener_top_monedas(60)
    alertas = []
    cercanas = []

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

            hoy = df.iloc[-1]
            ayer = df.iloc[-2]
            precio = hoy['close']
            min_hoy = min(hoy['low'], ayer['low']) # Incluye lo que toco hace unas horas
            rsi = hoy['RSI']

            # Filtro anticaida libre: RSI mayor a 30
            if rsi < 30:
                continue

            motivos = []

            # MOTOR 1: Rebote en SuperTrend Verde (revisando la mecha del dia)
            st_val = hoy['SuperTrend']
            dist_min_st = (hoy['low'] - st_val) / st_val
            dist_precio_st = (precio - st_val) / st_val

            if hoy['ST_Trend'] == 1 and st_val > 0:
                # Si la mecha de hoy se acerco a menos de 2.5% del SuperTrend y el precio actual sigue por encima (hasta 5.5%)
                if (-0.005 <= dist_min_st <= 0.025) and (0 <= dist_precio_st <= 0.055) and rsi <= 65:
                    motivos.append(f"🟩 Toque en SuperTrend (${st_val:.4f})")
                elif 0 < dist_precio_st <= 0.08:
                    cercanas.append((dist_precio_st * 100, f"• <b>{symbol}</b> (${precio:.4f}) a +{dist_precio_st*100:.1f}% de su SuperTrend Verde"))

            # MOTOR 2: Retroceso Fibonacci 61.8% - 71.3% (Impulso Alcista Real)
            ventana = df.iloc[-60:]
            min_impulso = ventana['low'].min()
            idx_min = ventana['low'].idxmin()
            ventana_post = df.loc[idx_min:]
            max_impulso = ventana_post['high'].max()
            rango = max_impulso - min_impulso

            if rango > 0 and len(ventana_post) >= 4 and precio < max_impulso * 0.96:
                fib_618 = max_impulso - (rango * 0.618)
                fib_713 = max_impulso - (rango * 0.713)
                fib_786 = max_impulso - (rango * 0.786)
                
                # Si el precio actual o la mecha de hoy toco la zona 61.8% - 78.6% y se mantiene sobre el 78.6%
                toco_fib = (fib_786 * 0.99 <= hoy['low'] <= fib_618 * 1.015) and (precio >= fib_786) and (precio <= fib_618 * 1.03)
                if toco_fib:
                    motivos.append(f"🎯 Toque Fib 61.8-71.3% (${fib_713:.4f} - ${fib_618:.4f})")

            # MOTOR 3: Soportes y Resistencias (Pisos y Retesteos con mecha del dia)
            soportes, resistencias = detectar_soportes_resistencias(df.iloc[-65:])
            soporte_usado = False
            for s in reversed(soportes):
                dist_mecha = (hoy['low'] - s) / s
                dist_cierre = (precio - s) / s
                # La mecha toco el soporte (-0.8% a +2%) y el precio reboto manteniendose arriba (0% a +4%)
                if (-0.008 <= dist_mecha <= 0.02) and (0 <= dist_cierre <= 0.04):
                    motivos.append(f"🧱 Rebote en Soporte (${s:.4f})")
                    soporte_usado = True
                    break

            if not soporte_usado:
                for res in reversed(resistencias):
                    dist_mecha = (hoy['low'] - res) / res
                    dist_cierre = (precio - res) / res
                    if (-0.008 <= dist_mecha <= 0.02) and (0 <= dist_cierre <= 0.04) and df['high'].iloc[-7:-1].max() > res * 1.02:
                        motivos.append(f"🔄 Retesteo de Techo Roto (${res:.4f})")
                        break

            # Si cumplio AL MENOS UNO de los 3 motores
            if motivos:
                atr = hoy['ATR']
                stop_loss = min(hoy['low'], precio - (1.2 * atr)) - (0.3 * atr)
                riesgo = precio - stop_loss
                if riesgo <= 0:
                    stop_loss = precio - (1.5 * atr)
                    riesgo = precio - stop_loss

                techos_arriba = [r for r in resistencias if r > precio * 1.03]
                techo_ref = min(techos_arriba) if techos_arriba else (precio + (atr * 3.0))

                tp1 = precio + (riesgo * 2.0)
                tp2 = max(techo_ref, precio + (riesgo * 3.0))

                pct_sl = ((stop_loss - precio) / precio) * 100
                pct_tp1 = ((tp1 - precio) / precio) * 100
                pct_tp2 = ((tp2 - precio) / precio) * 100

                etiqueta = "🔥 <b>CONFLUENCIA MULTIPLE</b>" if len(motivos) > 1 else "🟢 <b>SEÑAL SPOT 1D</b>"

                alertas.append(
                    f"{etiqueta}: <b>{symbol}</b>\n"
                    f"🔹 <b>Precio Actual:</b> ${precio:.4f} <i>(Mín hoy: ${hoy['low']:.4f})</i>\n"
                    f"📊 <b>Motor:</b> {' + '.join(motivos)}\n"
                    f"📈 <b>RSI (1D):</b> {rsi:.1f}\n"
                    f"🏛 <b>Próximo Techo:</b> ${techo_ref:.4f}\n"
                    f"🛑 <b>Stop Loss:</b> ${stop_loss:.4f} ({pct_sl:.1f}%)\n"
                    f"🎯 <b>Take Profit 1:</b> ${tp1:.4f} (+{pct_tp1:.1f}%)\n"
                    f"🎯 <b>Take Profit 2:</b> ${tp2:.4f} (+{pct_tp2:.1f}%)"
                )
        except Exception:
            continue

    if alertas:
        encabezado = f"🚀 <b>OPORTUNIDADES SPOT DETECTADAS (1D)</b>\nTotal hoy: {len(alertas)} monedas\n━━━━━━━━━━━━━━━━━━\n\n"
        enviar_telegram(encabezado + "\n\n━━━━━━━━━━━━━━━━━━\n\n".join(alertas[:12]))
    else:
        cercanas_ordenadas = [x[1] for x in sorted(cercanas, key=lambda x: x[0])[:5]]
        texto_cercanas = "\n".join(cercanas_ordenadas) if cercanas_ordenadas else "Sin monedas cercanas al SuperTrend."
        enviar_telegram(
            f"🔎 <b>Escaneo 1D completado (60 monedas)</b>\n"
            f"Ninguna tocó zona hoy, pero estas son las más cercanas a su soporte de SuperTrend:\n\n{texto_cercanas}"
        )

if __name__ == "__main__":
    escanear()
