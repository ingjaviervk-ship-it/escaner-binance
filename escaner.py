import os
import sys
import json
import requests
import pandas as pd
import numpy as np

# Asegurar codificación UTF-8 en consola para emojis
if sys.stdout and hasattr(sys.stdout, 'reconfigure'):
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

# =============================================================================
# CONFIGURACIÓN Y ARCHIVO DE ESTADO PERSISTENTE
# =============================================================================
TELEGRAM_TOKEN = (os.environ.get("TELEGRAM_TOKEN") or "").strip()
TELEGRAM_CHAT_ID = (os.environ.get("TELEGRAM_CHAT_ID") or "").strip()

# Tu capital inicial real configurado ($4,000 USD)
CAPITAL_INICIAL_DEFAULT = float(os.environ.get("CAPITAL_INICIAL") or 4000.0)
RIESGO_MAX_PCT = float(os.environ.get("RIESGO_MAX_PCT") or 0.02) # 2% institucional

BASE_URL = "https://data-api.binance.vision/api/v3"
STATE_FILE = os.path.join(os.path.dirname(__file__), "estado_cuenta.json")

def cargar_estado():
    """Carga el saldo acumulado real y las posiciones abiertas desde el JSON de GitHub."""
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            print(f"Aviso al leer estado: {e}")
            
    return {
        "capital_actual": CAPITAL_INICIAL_DEFAULT,
        "capital_inicial": CAPITAL_INICIAL_DEFAULT,
        "posiciones_abiertas": {},
        "historial_cerrados": []
    }

def guardar_estado(estado):
    """Guarda el saldo actualizado y las posiciones en el repositorio de GitHub."""
    try:
        with open(STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(estado, f, indent=4, ensure_ascii=False)
        print(f"Estado de cuenta guardado exitosamente: Capital actual = ${estado['capital_actual']:,.2f} USD")
    except Exception as e:
        print(f"Error al guardar estado de cuenta: {e}")

def enviar_telegram(mensaje):
    """Envía mensaje con formato HTML a Telegram."""
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        print("\n[VISTA PREVIA DE ALERTA TELEGRAM]")
        print(mensaje.replace("<b>", "").replace("</b>", "").replace("<i>", "").replace("</i>", ""))
        return
        
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": mensaje, "parse_mode": "HTML"}
    try:
        r = requests.post(url, json=payload, timeout=12)
        if r.status_code != 200:
            requests.post(url, json={"chat_id": TELEGRAM_CHAT_ID, "text": mensaje}, timeout=12)
    except Exception as e:
        print(f"Error al enviar a Telegram: {e}")

def obtener_top_monedas(limite=60):
    """Filtra las mejores criptomonedas de Binance por volumen en USDT."""
    excluir = [
        'USDCUSDT', 'FDUSDUSDT', 'TUSDUSDT', 'USDPUSDT', 'DAIUSDT', 
        'EURUSDT', 'PAXGUSDT', 'USD1USDT', 'USDEUSDT', 'BUSDUSDT', 'AEURUSDT'
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
            for fijo in ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT", "ADAUSDT", "DOGEUSDT", "AVAXUSDT", "LINKUSDT", "LTCUSDT"]:
                if fijo not in lista:
                    lista.append(fijo)
            return lista
    except Exception as e:
        print(f"Error al obtener tickers de Binance: {e}")
        
    return ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT", "ADAUSDT", "DOGEUSDT", "AVAXUSDT", "LINKUSDT", "LTCUSDT"]

def calcular_indicadores(df):
    """Calcula EMA 50, EMA 100, EMA 200, ATR, CCI y Canales Donchian."""
    close = df['close']
    high = df['high']
    low = df['low']
    
    df['EMA50'] = close.ewm(span=50, adjust=False).mean()
    df['EMA100'] = close.ewm(span=100, adjust=False).mean()
    df['EMA200'] = close.ewm(span=200, adjust=False).mean()
    
    tr1 = high - low
    tr2 = (high - close.shift(1)).abs()
    tr3 = (low - close.shift(1)).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    df['ATR'] = tr.ewm(alpha=1/14, adjust=False).mean()
    df['SMA_ATR'] = df['ATR'].rolling(20).mean()
    
    tp = (high + low + close) / 3
    sma_tp = tp.rolling(20).mean()
    mad = tp.rolling(20).apply(lambda x: np.mean(np.abs(x - np.mean(x))), raw=True)
    df['CCI'] = (tp - sma_tp) / (0.015 * mad + 1e-10)
    
    df['High20'] = high.shift(1).rolling(20).max()
    df['Low10'] = low.shift(1).rolling(10).min()
    df['Low20'] = low.shift(1).rolling(20).min()
    df['High10'] = high.shift(1).rolling(10).max()
    return df

def calcular_gestion_capital(precio, stop_loss, capital_actual, riesgo_pct=RIESGO_MAX_PCT):
    """Calcula el tamaño de la orden con la Opción 5 sobre el CAPITAL ACTUALIZADO."""
    distancia_pct = abs(precio - stop_loss) / precio
    if distancia_pct <= 0:
        distancia_pct = 0.05
        
    riesgo_permitido_usd = capital_actual * riesgo_pct
    tamano_posicion_usd = riesgo_permitido_usd / distancia_pct
    
    # Límite de seguridad: máximo el 40% del capital actual en un solo activo
    max_permitido_usd = capital_actual * 0.40
    tamano_final_usd = min(tamano_posicion_usd, max_permitido_usd)
    
    cantidad_monedas = tamano_final_usd / precio
    efectivo_reserva_usd = max(0.0, capital_actual - tamano_final_usd)
    
    return {
        'riesgo_usd': riesgo_permitido_usd,
        'distancia_pct': distancia_pct * 100.0,
        'tamano_usd': tamano_final_usd,
        'tamano_monedas': cantidad_monedas,
        'reserva_usd': efectivo_reserva_usd,
        'pct_cuenta': (tamano_final_usd / capital_actual) * 100.0
    }

def ejecutar_bot_inteligente():
    estado = cargar_estado()
    cap_actual = estado['capital_actual']
    posiciones = estado.get('posiciones_abiertas', {})
    
    print("\n" + "="*80)
    print(f"BOT CUANTITATIVO CON ESTADO PERSISTENTE EN GITHUB")
    print(f"Capital Inicial: ${estado['capital_inicial']:,.2f} USD | Capital Actualizado: ${cap_actual:,.2f} USD")
    print(f"Riesgo por Operación (2%): ${cap_actual * RIESGO_MAX_PCT:,.2f} USD | Posiciones Abiertas: {len(posiciones)}")
    print("="*80)
    
    monedas = obtener_top_monedas(60)
    alertas_entrada = []
    alertas_salida = []
    radar_seguimiento = []
    
    # -------------------------------------------------------------------------
    # FASE 1: MONITOREO DE POSICIONES ABIERTAS (¿TOCÓ TRAILING STOP O SALIDA?)
    # -------------------------------------------------------------------------
    symbols_a_cerrar = []
    for sym, pos in posiciones.items():
        try:
            r = requests.get(f"{BASE_URL}/ticker/price", params={"symbol": sym}, timeout=6)
            if r.status_code == 200:
                p_actual = float(r.json()['price'])
                p_entrada = pos['precio_entrada']
                sl_actual = pos['stop_loss']
                trailing_stop = pos.get('trailing_stop', sl_actual)
                highest_seen = max(pos.get('highest_price', p_entrada), p_actual)
                pos['highest_price'] = highest_seen
                
                # Actualizar Trailing Stop (sube con cada nuevo máximo)
                atr_ref = pos.get('atr_entry', p_entrada * 0.04)
                nuevo_trailing = highest_seen - (2.5 * atr_ref)
                if nuevo_trailing > trailing_stop:
                    pos['trailing_stop'] = nuevo_trailing
                    trailing_stop = nuevo_trailing
                    
                # Evaluar si tocó el Stop Loss o el Trailing Stop
                if p_actual <= trailing_stop:
                    pnl_dolares = (p_actual - p_entrada) * pos['cantidad_monedas']
                    pnl_pct = (p_actual - p_entrada) / p_entrada * 100.0
                    
                    cap_actual += pnl_dolares
                    estado['capital_actual'] = cap_actual
                    symbols_a_cerrar.append(sym)
                    
                    icono_res = "🟢" if pnl_dolares > 0 else "🔴"
                    alertas_salida.append(
                        f"🚪 <b>CIERRE DE POSICIÓN: {sym}</b>\n"
                        f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
                        f"🔹 <b>Estrategia:</b> {pos['metodo']}\n"
                        f"💵 <b>Precio de Entrada:</b> ${p_entrada:,.4f}\n"
                        f"🏁 <b>Precio de Salida:</b> ${p_actual:,.4f}\n"
                        f"{icono_res} <b>Resultado:</b> {pnl_pct:+.2f}% (<b>{pnl_dolares:+,.2f} USD</b>)\n"
                        f"💰 <b>NUEVO CAPITAL DISPONIBLE:</b> <b>${cap_actual:,.2f} USD</b>\n"
                        f"━━━━━━━━━━━━━━━━━━━━━━━━"
                    )
        except Exception as e:
            print(f"Aviso al monitorear posición {sym}: {e}")
            
    for sym in symbols_a_cerrar:
        estado['historial_cerrados'].append(posiciones[sym])
        del posiciones[sym]
        
    # -------------------------------------------------------------------------
    # FASE 2: ESCANEO DE NUEVAS OPORTUNIDADES (100% COMPRAS SPOT)
    # -------------------------------------------------------------------------
    for symbol in monedas:
        if symbol in posiciones:
            continue
            
        try:
            url = f"{BASE_URL}/klines"
            params = {"symbol": symbol, "interval": "1d", "limit": 220}
            r = requests.get(url, params=params, timeout=8)
            if r.status_code != 200:
                continue
                
            df = pd.DataFrame(r.json(), columns=[
                'time', 'open', 'high', 'low', 'close', 'vol',
                'close_time', 'qav', 'num_trades', 'taker_base', 'taker_quote', 'ignore'
            ])
            for col in ['open', 'high', 'low', 'close', 'vol']:
                df[col] = df[col].astype(float)
                
            df = calcular_indicadores(df)
            hoy = df.iloc[-1]
            ayer = df.iloc[-2]
            precio = hoy['close']
            atr = hoy['ATR']
            
            # Método 1: Donchian Breakout 20D (Spot)
            if (precio > hoy['High20']) and (ayer['close'] <= ayer['High20']) and (precio > hoy['EMA100']):
                sl = max(hoy['Low10'], precio - (2.5 * atr))
                alertas_entrada.append({
                    'symbol': symbol, 'metodo': 'Donchian Breakout 20D (Turtle)',
                    'tipo': '🟢 COMPRA SPOT / LONG', 'icono': '🐢', 'precio': precio, 'stop_loss': sl, 'atr': atr
                })
            # Método 2: Golden Cross Institucional (Spot)
            elif (hoy['EMA50'] > hoy['EMA200']) and (ayer['EMA50'] <= ayer['EMA200'] or (ayer['low'] <= hoy['EMA50']*1.01 and precio > hoy['EMA50'])) and (precio > hoy['EMA100']):
                sl = precio - (2.5 * atr)
                alertas_entrada.append({
                    'symbol': symbol, 'metodo': 'Golden Cross Institucional',
                    'tipo': '🟢 COMPRA SPOT / LONG', 'icono': '🏛️', 'precio': precio, 'stop_loss': sl, 'atr': atr
                })
            # Método 3: HobbieCode Bot Cuántico (Spot)
            elif (precio > hoy['EMA100']) and (atr > hoy['SMA_ATR']) and (hoy['CCI'] > 0) and (ayer['CCI'] <= 0):
                sl = precio - (2.5 * atr)
                alertas_entrada.append({
                    'symbol': symbol, 'metodo': 'HobbieCode Bot Cuántico',
                    'tipo': '🟢 COMPRA SPOT / LONG', 'icono': '🎯', 'precio': precio, 'stop_loss': sl, 'atr': atr
                })
            else:
                dist_max20 = (hoy['High20'] - precio) / precio * 100.0
                if 0 < dist_max20 <= 2.5 and precio > hoy['EMA100']:
                    radar_seguimiento.append((dist_max20, f"• <b>{symbol}</b> a <b>{dist_max20:.1f}%</b> de romper Máx 20D (${hoy['High20']:.4f})"))
        except Exception:
            continue
            
    # -------------------------------------------------------------------------
    # FASE 3: ENVIAR MENSAJES Y GESTIONAR CUPOS (MÁXIMO 3 POSICIONES)
    # -------------------------------------------------------------------------
    for msg_salida in alertas_salida:
        enviar_telegram(msg_salida)
        
    MAX_POSICIONES = 3
    cupos_disponibles = max(0, MAX_POSICIONES - len(posiciones))
    
    if alertas_entrada and cupos_disponibles > 0:
        alertas_a_ejecutar = alertas_entrada[:cupos_disponibles]
        
        for a in alertas_a_ejecutar:
            gestion = calcular_gestion_capital(a['precio'], a['stop_loss'], capital_actual=cap_actual)
            
            posiciones[a['symbol']] = {
                'metodo': a['metodo'],
                'precio_entrada': a['precio'],
                'cantidad_monedas': gestion['tamano_monedas'],
                'inversion_usd': gestion['tamano_usd'],
                'stop_loss': a['stop_loss'],
                'trailing_stop': a['stop_loss'],
                'highest_price': a['precio'],
                'atr_entry': a['atr']
            }
            
            msg = (
                f"{a['icono']} <b>NUEVA SEÑAL SPOT: {a['symbol']}</b>\n"
                f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
                f"🔹 <b>Estrategia:</b> {a['metodo']}\n"
                f"🎯 <b>Acción:</b> <b>{a['tipo']}</b>\n"
                f"💵 <b>Precio de Entrada:</b> ${a['precio']:,.4f}\n"
                f"🛑 <b>Stop Loss:</b> ${a['stop_loss']:,.4f} <i>(-{gestion['distancia_pct']:.1f}%)</i>\n\n"
                f"🧮 <b>GESTIÓN MONETARIA (OPCIÓN 5 - REGLA 2%):</b>\n"
                f"• Capital Actual de la Cuenta: <b>${cap_actual:,.2f} USD</b>\n"
                f"• Riesgo Máximo Asumido (2%): <b>${gestion['riesgo_usd']:,.2f} USD</b>\n"
                f"• <b>Tamaño a Comprar:</b> <b>${gestion['tamano_usd']:,.2f} USD</b> ({gestion['pct_cuenta']:.1f}% de tu saldo)\n"
                f"• <b>Cantidad en Monedas:</b> <b>{gestion['tamano_monedas']:.4f} {a['symbol'].replace('USDT', '')}</b>\n"
                f"• Saldo en Reserva: <b>${gestion['reserva_usd']:,.2f} USD</b>\n"
                f"• Cupos Ocupados: <b>{len(posiciones)} de {MAX_POSICIONES}</b>\n"
                f"━━━━━━━━━━━━━━━━━━━━━━━━"
            )
            enviar_telegram(msg)
            
        if len(alertas_entrada) > cupos_disponibles:
            monedas_excedentes = [x['symbol'] for x in alertas_entrada[cupos_disponibles:]]
            msg_excedente = (
                f"⚠️ <b>CARTERA AL MÁXIMO DE CAPACIDAD ({len(posiciones)}/{MAX_POSICIONES})</b>\n"
                f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
                f"Se detectaron señales válidas en: <b>{', '.join(monedas_excedentes)}</b>\n"
                f"🛡 No se abren para no sobreexponer tu cuenta de ${cap_actual:,.2f} USD.\n"
                f"Quedan en lista de espera hasta que se cierre una posición activa.\n"
                f"━━━━━━━━━━━━━━━━━━━━━━━━"
            )
            enviar_telegram(msg_excedente)
            
    elif alertas_entrada and cupos_disponibles == 0:
        monedas_excedentes = [x['symbol'] for x in alertas_entrada[:4]]
        msg_full = (
            f"⚠️ <b>CARTERA COMPLETA ({len(posiciones)}/{MAX_POSICIONES} POSICIONES ACTIVAS)</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"Se detectaron señales en: <b>{', '.join(monedas_excedentes)}</b>\n"
            f"🛡 Tu capital está 100% protegido en tus 3 posiciones actuales.\n"
            f"No se realizan nuevas compras hasta que el bot cierre una posición.\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━"
        )
        enviar_telegram(msg_full)
        
    elif not alertas_salida:
        top_radar = [x[1] for x in sorted(radar_seguimiento, key=lambda x: x[0])[:6]]
        txt_radar = "\n".join(top_radar) if top_radar else "Ninguna moneda en zona de ruptura."
        
        msg_quiet = (
            f"🔎 <b>INFORME DE MERCADO ({len(monedas)} MONEDAS)</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"💰 <b>Capital Actual:</b> ${cap_actual:,.2f} USD\n"
            f"📊 <b>Posiciones Abiertas:</b> {len(posiciones)} de {MAX_POSICIONES}\n"
            f"✅ 0 entradas nuevas confirmadas en este escaneo.\n\n"
            f"👀 <b>RADAR (Más cerca de romper Máx 20D):</b>\n"
            f"{txt_radar}\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━"
        )
        enviar_telegram(msg_quiet)
        
    estado['posiciones_abiertas'] = posiciones
    guardar_estado(estado)

if __name__ == "__main__":
    ejecutar_bot_inteligente()
