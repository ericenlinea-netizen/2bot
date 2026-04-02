import requests
import time
import statistics

# ================= TELEGRAM =================
TOKEN = "8329327841:AAE_oEg3pFrmVL3SAjiHe_VaU8AuoL5xdL0"
CHAT_ID = "8329327841"

def enviar_alerta(msg):
    try:
        requests.post(
            f"https://api.telegram.org/bot{TOKEN}/sendMessage",
            data={"chat_id": CHAT_ID, "text": msg, "parse_mode": "HTML"}
        )
    except:
        pass

# ================= CONFIG =================
symbols = ["BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT", "ADAUSDT"]

estado = False
entrada = 0
max_precio = 0
symbol_activo = None
racha_perdidas = 0
ganancia_acumulada = 0
operaciones_totales = 0
operaciones_ganadoras = 0

enviar_alerta("📊 <b>BOT CUANTITATIVO V2 ACTIVO</b>")

# ================= FUNCIONES DE DATOS =================
def get_klines(symbol, interval, limit=50):
    data = requests.get(
        f"https://api.binance.com/api/v3/klines?symbol={symbol}&interval={interval}&limit={limit}"
    ).json()
    cierres  = [float(x[4]) for x in data]
    altos    = [float(x[2]) for x in data]
    bajos    = [float(x[3]) for x in data]
    volumenes = [float(x[5]) for x in data]
    return cierres, altos, bajos, volumenes

# ================= INDICADORES =================
def ema(cierres, n):
    k = 2 / (n + 1)
    e = cierres[0]
    for c in cierres[1:]:
        e = c * k + e * (1 - k)
    return e

def ema_serie(cierres, n):
    k = 2 / (n + 1)
    result = [cierres[0]]
    for c in cierres[1:]:
        result.append(c * k + result[-1] * (1 - k))
    return result

def rsi(cierres, n=14):
    ganancias = []
    perdidas = []
    for i in range(1, len(cierres)):
        diff = cierres[i] - cierres[i-1]
        if diff > 0:
            ganancias.append(diff)
            perdidas.append(0)
        else:
            ganancias.append(0)
            perdidas.append(abs(diff))
    if len(ganancias) < n:
        return 50
    ag = sum(ganancias[-n:]) / n
    ap = sum(perdidas[-n:]) / n
    if ap == 0:
        return 100
    rs = ag / ap
    return 100 - (100 / (1 + rs))

def atr(altos, bajos, cierres, n=14):
    trs = []
    for i in range(1, len(cierres)):
        tr = max(
            altos[i] - bajos[i],
            abs(altos[i] - cierres[i-1]),
            abs(bajos[i] - cierres[i-1])
        )
        trs.append(tr)
    return sum(trs[-n:]) / n if len(trs) >= n else sum(trs) / len(trs)

def tendencia_ema(cierres):
    e8  = ema(cierres[-20:], 8)
    e21 = ema(cierres[-30:], 21)
    e50 = ema(cierres[-50:], 50) if len(cierres) >= 50 else ema(cierres, len(cierres))
    # Tendencia alcista si EMA8 > EMA21 > EMA50
    return e8 > e21 > e50

def volumen_creciente(volumenes):
    vol_reciente = sum(volumenes[-3:]) / 3
    vol_base     = sum(volumenes[-10:-3]) / 7
    return vol_reciente > vol_base * 1.3  # 30% más de volumen

def detectar_pullback_avanzado(cierres, altos, bajos):
    # Tendencia previa al alza
    subida = all(cierres[-7+i] < cierres[-6+i] for i in range(4))
    # Retroceso suave (no más de 0.8% desde el máximo reciente)
    maximo = max(cierres[-7:-2])
    retroceso = (maximo - cierres[-2]) / maximo < 0.008
    # Vela de recuperación
    cuerpo_actual = cierres[-1] - bajos[-1]
    rango_actual  = altos[-1] - bajos[-1]
    recuperacion  = cierres[-1] > cierres[-2] and (rango_actual > 0 and cuerpo_actual / rango_actual > 0.5)
    return subida and retroceso and recuperacion

def ruptura_resistencia_reciente(cierres):
    resistencia = max(cierres[-20:-2])
    return cierres[-1] > resistencia * 0.999  # cerca o por encima

def score_avanzado(cierres, altos, bajos, volumenes):
    precio = cierres[-1]
    s = 0
    razones = []

    r = rsi(cierres)
    if 50 < r < 70:
        s += 3
        razones.append(f"RSI {r:.0f}✅")
    elif r >= 70:
        s -= 2  # sobrecomprado
        razones.append(f"RSI {r:.0f}⚠️")

    if tendencia_ema(cierres):
        s += 3
        razones.append("EMA alcista✅")

    if detectar_pullback_avanzado(cierres, altos, bajos):
        s += 2
        razones.append("Pullback✅")

    if volumen_creciente(volumenes):
        s += 2
        razones.append("Volumen✅")

    if ruptura_resistencia_reciente(cierres):
        s += 2
        razones.append("Ruptura✅")

    momento = (cierres[-1] - cierres[-4]) / cierres[-4]
    if momento > 0.002:
        s += 1
        razones.append("Momento✅")

    return s, razones

# ================= LOOP =================
while True:
    try:

        # ================= GESTIÓN POSICIÓN ABIERTA =================
        if estado:
            cierres, altos, bajos, volumenes = get_klines(symbol_activo, "1m", 20)
            precio = cierres[-1]
            atr_val = atr(altos, bajos, cierres)

            if precio > max_precio:
                max_precio = precio

            ganancia = precio - entrada
            ganancia_pct = (ganancia / entrada) * 100

            sl = max(min(cierres[-5:]), entrada - atr_val * 1.5)
            tp = entrada + atr_val * 3  # RR 1:2 mínimo

            trailing_activado = (max_precio - entrada) > atr_val
            trailing_sl = max_precio - atr_val * 0.8

            if precio <= sl:
                operaciones_totales += 1
                enviar_alerta(
                    f"🛑 <b>SL {symbol_activo}</b>\n"
                    f"Precio: {precio:.4f}\n"
                    f"P&amp;L: {ganancia_pct:.2f}%\n"
                    f"Ops: {operaciones_ganadoras}/{operaciones_totales}"
                )
                estado = False
                racha_perdidas += 1

            elif precio >= tp:
                operaciones_totales += 1
                operaciones_ganadoras += 1
                ganancia_acumulada += ganancia
                enviar_alerta(
                    f"💰 <b>TP {symbol_activo}</b>\n"
                    f"Precio: {precio:.4f}\n"
                    f"P&amp;L: +{ganancia_pct:.2f}%\n"
                    f"Acumulado: +{ganancia_acumulada:.4f}"
                )
                estado = False
                racha_perdidas = 0

            elif trailing_activado and precio <= trailing_sl:
                operaciones_totales += 1
                operaciones_ganadoras += 1
                ganancia_acumulada += ganancia
                enviar_alerta(
                    f"✅ <b>TRAILING {symbol_activo}</b>\n"
                    f"Precio: {precio:.4f}\n"
                    f"P&amp;L: +{ganancia_pct:.2f}%"
                )
                estado = False
                racha_perdidas = 0

            # Salida de emergencia si RSI se dispara (sobrecomprado extremo)
            elif rsi(cierres) > 80:
                operaciones_totales += 1
                operaciones_ganadoras += 1 if ganancia > 0 else 0
                ganancia_acumulada += ganancia
                enviar_alerta(f"⚠️ <b>SALIDA RSI {symbol_activo}</b>\nRSI extremo, cerrando\nP&amp;L: {ganancia_pct:.2f}%")
                estado = False

            time.sleep(5)
            continue

        # ================= PROTECCIONES =================
        if ganancia_acumulada >= 10:
            enviar_alerta("🛑 <b>META DE GANANCIA ALCANZADA</b>\nPausando 3 minutos...")
            time.sleep(180)
            ganancia_acumulada = 0
            continue

        if racha_perdidas >= 3:
            enviar_alerta("⛔ <b>3 PÉRDIDAS SEGUIDAS</b>\nPausando 5 minutos...")
            time.sleep(300)
            racha_perdidas = 0
            continue

        # ================= FILTRO BTC (mercado macro) =================
        btc_1m, _, _, btc_vol_1m = get_klines("BTCUSDT", "1m", 50)
        btc_5m, _, _, _          = get_klines("BTCUSDT", "5m", 50)
        btc_15m, _, _, _         = get_klines("BTCUSDT", "15m", 50)

        btc_ok = tendencia_ema(btc_1m) and tendencia_ema(btc_5m) and tendencia_ema(btc_15m)
        btc_rsi = rsi(btc_1m)

        if not btc_ok or btc_rsi > 75:
            time.sleep(8)
            continue

        # ================= SCAN =================
        mejor = None
        mejor_score = 0
        mejor_razones = []

        for symbol in symbols:
            if symbol == "BTCUSDT":
                continue

            cierres, altos, bajos, volumenes = get_klines(symbol, "1m", 50)
            cierres_5m, altos_5m, bajos_5m, _ = get_klines(symbol, "5m", 50)

            precio = cierres[-1]
            atr_val = atr(altos, bajos, cierres)

            # Filtros obligatorios
            if not tendencia_ema(cierres):
                continue
            if not tendencia_ema(cierres_5m):
                continue
            if not volumen_creciente(volumenes):
                continue

            r = rsi(cierres)
            if r < 45 or r > 72:
                continue

            s, razones = score_avanzado(cierres, altos, bajos, volumenes)

            # Verificar RR mínimo
            sl_est = max(min(cierres[-5:]), precio - atr_val * 1.5)
            riesgo = precio - sl_est
            if riesgo <= 0 or riesgo > atr_val * 2:
                continue

            if s > mejor_score:
                mejor_score = s
                mejor = (symbol, precio, cierres, altos, bajos, atr_val)
                mejor_razones = razones

        # ================= ENTRADA =================
        if mejor and mejor_score >= 9:
            symbol_temp, precio_temp, cierres_temp, altos_temp, bajos_temp, atr_val = mejor

            sl = max(min(cierres_temp[-5:]), precio_temp - atr_val * 1.5)
            tp = precio_temp + atr_val * 3
            riesgo_pct = ((precio_temp - sl) / precio_temp) * 100

            symbol_activo = symbol_temp
            entrada = precio_temp
            max_precio = entrada
            estado = True

            enviar_alerta(
                f"🚀 <b>ENTRY {symbol_activo}</b>\n"
                f"Precio: {entrada:.4f}\n"
                f"SL: {sl:.4f} ({riesgo_pct:.2f}%)\n"
                f"TP: {tp:.4f}\n"
                f"Score: {mejor_score}/14\n"
                f"Señales: {' | '.join(mejor_razones)}"
            )

        time.sleep(8)

    except Exception as e:
        print(f"Error: {e}")
        time.sleep(10)
