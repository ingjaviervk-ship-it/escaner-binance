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
            lista = [p['symbol'] for p in pares_ordenados[:limite]]
            for fijo in ["BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "AVAXUSDT", "BNBUSDT"]:
                if fijo not in lista:
                    lista.append(fijo)
            return lista
    except Exception:
        pass
    return ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT", "ADAUSDT", "DOGEUSDT", "AVAXUSDT", "LINKUSDT", "SUIUSDT"]

def calcular_rsi(series, period=14):
    delta = series.diff()
    gain = (delta.where(delta > 0, 0)).ewm(alpha=1/period, adjust=False).mean()
    loss = (-delta.where(delta < 0, 0)).ewm(alpha=1/period, adjust=False).mean()
    rs = gain / loss
    return 100 - (100 / (1 + rs))

def calcular_supertrend(df, period=10, multiplier=3.0):
    """Calibrado exactamente con SUPERTREND(10,3) de la app de Binance"""
    high = df['high']
    low = df['low']
    close = df['close']
    
    tr1 = high - low
    tr2 = (high - close.shift(1)).abs()
    tr3 = (low - close.shift(1)).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    
    # ATR de Wilder (RMA) identico al usado en Binance
    atr = tr.ewm(alpha=1/period, adjust=False).mean()
    
    hl2 = (high + low) / 2
    basic_ub = (hl2 + (multiplier * atr)).values
    basic_lb = (hl2 - (multiplier * atr)).values
    close_vals = close.values
    
    final_ub = np.zeros(len(df))
    final_lb = np.zeros(len(df))
    st = np.zeros(len(df))
    trend = np.ones(len(df)) # 1 = Verde, -1 = Rojo
    
    final_ub[0] = basic_ub[0]
    final_lb[0] = basic_lb[0]
    
    for i in range(1, len(df)):
        # Banda superior
        if basic_ub[i] < final_ub[i-1] or close_vals[i-1] > final_ub[i-1]:
            final_ub[i] = basic_ub[i]
        else:
            final_ub[i] = final_ub[i-1]
            
        # Banda inferior (Soporte Verde)
        if basic_lb[i] > final_lb[i-1] or close_vals[i-1] < final_lb[i-1]:
            final_lb[i] = basic_lb[i]
        else:
            final_lb[i] = final_lb[i-1]
            
        # Direccion de tendencia evaluada en la vela actual (como en Binance)
        if trend[i-1] == -1 and close_vals[i] > final_ub[i-1]:
            trend[i] = 1
        elif trend[i-1] == 1 and close_vals[i] < final_lb[i-1]:
            trend[i] = -1
        else:
            trend[i] = trend[i-1]
            
        st[i] = final_lb[i] if trend[i] == 1 else final_ub[i]
        
    df['ATR'] = atr
    df['SuperTrend'] = st
    df['ST_Trend'] = trend
    return df

def detectar_soportes_resistencias(df):
    soportes, resistencias = [], []
    for i in range(3, len(df) - 2):
        if df['low'].iloc[i] == df['low'].iloc[i-3:i+3].min():
            soportes.append(df['low'].iloc[i])
        if df['high'].iloc[i] == df['high'].iloc[i-3:i+3].max():
            resistencias.append(df['high'].iloc[i])
    return soportes, resistencias

def detectar_patrones(hoy, ayer, soportes):
    patrones = []
    for nombre, v in [("Hoy", hoy), ("Vela Previa", ayer)]:
        cuerpo = abs(v['close'] - v['open'])
        rango = v['high'] - v['low']
        mecha_inf = min(v['open'], v['close']) - v['low']
        mecha_sup = v['high'] - max(v['open'], v['close'])
        if rango > 0 and mecha_inf >= (cuerpo * 1.8) and mecha_inf > mecha_sup * 1.4:
            patrones.append(f"🔨 Martillo ({nombre})")
            break

    if (ayer['close'] < ayer['open']) and (hoy['close'] > hoy['open']) and (hoy['close'] >= ayer['open']):
        patrones.append("🕯 Envolvente Alcista")

    for p in soportes[-3:]:
        if abs(min(hoy['low'], ayer['low']) - p) / p <= 0.015 and hoy['close'] > p:
            patrones.append("📐 Doble Piso (W)")
            break
    return patrones

def escanear():
    monedas = obtener_top_monedas(60)
    alertas = []
    radar_verdes = []
    diag_xrp = ""

    for symbol in monedas:
        try:
            r = requests.get(f"{BASE_URL}/klines", params={"symbol": symbol, "interval": "1d", "limit": 120}, timeout=10)
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
            min_2dias = min(hoy['low'], ayer['low'])
            rsi = hoy['RSI']
            st_hoy = hoy['SuperTrend']
            st_ayer = ayer['SuperTrend']

            if st_hoy <= 0:
                continue

            if symbol == "XRPUSDT":
                color_xrp = "🟩 Verde" if hoy['ST_Trend'] == 1 else "🟥 Rojo"
                diag_xrp = f"\n🔎 <b>Datos leídos en XRPUSDT:</b> Precio ${precio:.4f} | ST: ${st_hoy:.4f} ({color_xrp}) | Mín 48h: ${min_2dias:.4f} | RSI: {rsi:.1f}"

            # RADAR: UNICAMENTE monedas con SuperTrend VERDE
            if hoy['ST_Trend'] == 1 and precio >= st_hoy * 0.99:
                dist_verde = (precio - st_hoy) / st_hoy
                radar_verdes.append((abs(dist_verde) * 100, f"• <b>{symbol}</b> (${precio:.4f}) a <b>{dist_verde*100:+.2f}%</b> de ST Verde 🟩 (${st_hoy:.4f})"))

            if rsi < 28:
                continue

            motivos = []

            # MOTOR 1: SuperTrend VERDE (Permite mechazo de hasta -3.5% como el 1.2891 de XRP si el precio recupera)
            toco_st_hoy = (hoy['ST_Trend'] == 1) and (-0.035 <= (hoy['low'] - st_hoy) / st_hoy <= 0.035)
            toco_st_ayer = (ayer['ST_Trend'] == 1) and (-0.035 <= (ayer['low'] - st_ayer) / st_ayer <= 0.035)
            sigue_sobre_st = (hoy['ST_Trend'] == 1) and (-0.005 <= (precio - st_hoy) / st_hoy <= 0.06)

            if (toco_st_hoy or toco_st_ayer) and sigue_sobre_st and rsi <= 66:
                momento = "Hoy" if toco_st_hoy else "Vela Previa"
                motivos.append(f"🟩 Apoyo SuperTrend Verde ({momento}: ${st_hoy:.4f})")

            # MOTOR 2: Retroceso Fibonacci 61.8% - 71.3% (Hoy + Vela Previa)
            ventana = df.iloc[-65:]
            min_impulso = ventana['low'].min()
            idx_min = ventana['low'].idxmin()
            ventana_post = df.loc[idx_min:]
            max_impulso = ventana_post['high'].max()
            rango = max_impulso - min_impulso

            if rango > 0 and len(ventana_post) >= 4 and precio < max_impulso * 0.96:
                fib_618 = max_impulso - (rango * 0.618)
                fib_713 = max_impulso - (rango * 0.713)
                fib_786 = max_impulso - (rango * 0.786)
                
                toco_fib_2dias = (fib_786 * 0.985 <= min_2dias <= fib_618 * 1.025) and (fib_786 <= precio <= fib_618 * 1.045)
                if toco_fib_2dias:
                    motivos.append(f"🎯 Zona Fib 61.8-71.3% (${fib_713:.4f} - ${fib_618:.4f})")

            # MOTOR 3: Soportes y Resistencias (Hoy + Vela Previa)
            soportes, resistencias = detectar_soportes_resistencias(df.iloc[-65:])
            soporte_usado = False
            for s in reversed(soportes):
                toco_soporte = (-0.015 <= (hoy['low'] - s) / s <= 0.022) or (-0.015 <= (ayer['low'] - s) / s <= 0.022)
                en_rebote = (-0.003 <= (precio - s) / s <= 0.05)
                if toco_soporte and en_rebote:
                    motivos.append(f"🧱 Rebote en Soporte (${s:.4f})")
                    soporte_usado = True
                    break

            if not soporte_usado:
                for res in reversed(resistencias):
                    toco_retest = (-0.015 <= (hoy['low'] - res) / res <= 0.022) or (-0.015 <= (ayer['low'] - res) / res <= 0.022)
                    en_rebote = (-0.003 <= (precio - res) / res <= 0.05)
                    if toco_retest and en_rebote and df['high'].iloc[-8:-1].max() > res * 1.02:
                        motivos.append(f"🔄 Retesteo Techo Roto (${res:.4f})")
                        break

            if motivos:
                patrones = detectar_patrones(hoy, ayer, soportes)
                txt_patron = f"\n🕯 <b>Patrón:</b> {' + '.join(patrones)}" if patrones else ""

                atr = hoy['ATR']
                stop_loss = min(min_2dias, precio - (1.2 * atr)) - (0.3 * atr)
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

                etiqueta = "🔥 <b>CONFLUENCIA MULTIPLE</b>" if (len(motivos) > 1 or patrones) else "🟢 <b>SEÑAL SPOT 1D</b>"

                alertas.append(
                    f"{etiqueta}: <b>{symbol}</b>\n"
                    f"🔹 <b>Precio Actual:</b> ${precio:.4f} <i>(Mín 48h: ${min_2dias:.4f})</i>\n"
                    f"📊 <b>Motor:</b> {' + '.join(motivos)}{txt_patron}\n"
                    f"📈 <b>RSI (1D):</b> {rsi:.1f} | <b>ST:</b> ${st_hoy:.4f}\n"
                    f"🏛 <b>Próximo Techo:</b> ${techo_ref:.4f}\n"
                    f"🛑 <b>Stop Loss:</b> ${stop_loss:.4f} ({pct_sl:.1f}%)\n"
                    f"🎯 <b>Take Profit 1:</b> ${tp1:.4f} (+{pct_tp1:.1f}%)\n"
                    f"🎯 <b>Take Profit 2:</b> ${tp2:.4f} (+{pct_tp2:.1f}%)"
                )
        except Exception:
            continue

    top_verdes = [x[1] for x in sorted(radar_verdes, key=lambda x: x[0])[:6]]
    txt_radar = "\n".join(top_verdes) if top_verdes else "Ninguna en SuperTrend Verde."
    bloque_radar = f"\n\n👀 <b>MÁS PEGADAS A SUPERTREND VERDE 🟩:</b>\n{txt_radar}{diag_xrp}"

    if alertas:
        encabezado = f"🚀 <b>ALERTAS SPOT (HOY + VELA PREVIA)</b>\nTotal detectadas: {len(alertas)}\n━━━━━━━━━━━━━━━━━━\n\n"
        cuerpo = "\n\n━━━━━━━━━━━━━━━━━━\n\n".join(alertas[:10])
        enviar_telegram(encabezado + cuerpo + bloque_radar)
    else:
        enviar_telegram(
            f"🔎 <b>Escaneo 1D (Hoy + Vela Previa completado)</b>\n"
            f"Ninguna dio gatillo cerrado en las últimas 48h.{bloque_radar}"
        )

if __name__ == "__main__":
    escanear()
