import requests
import time

# ================= TELEGRAM =================
TOKEN = "8329327841:AAE_oEg3pFrmVL3SAjiHe_VaU8AuoL5xdL0"
CHAT_ID = "5019372975"

def enviar_alerta(msg):
    try:
        requests.post(
            f"https://api.telegram.org/bot{TOKEN}/sendMessage",
            data={"chat_id": CHAT_ID, "text": msg, "parse_mode": "HTML"}
        )
    except:
        pass

# ================= CONFIG AGRESIVA =================
symbols = [
    "BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT",
    "XRPUSDT", "ADAUSDT", "DOGEUSDT", "AVAXUSDT",
    "LINKUSDT", "DOTUSDT", "MATICUSDT", "LTCUSDT"
]

estado = False
entrada = 0
max_precio = 0
symbol_activo = None
racha_perdidas = 0
ganancia_acumulada = 0
operaciones_totales = 0
operaciones_ganadoras = 0

enviar_alerta("⚡ <b>BOT AGRESIVO V3 ACTIVO</b>")

# ================= INDICADORES =================
def get_klines(symbol, interval, limit=50):
    data = requests.get(
        f"https://api.binance.com/api/v3/klines?symbol={symbol}&interval={interval}&limit={limit}"
    ).json()
    cierres   = [float(x[4]) for x in data]
    altos     = [float(x[2]) for x in data]
    bajos     = [float(x[3]) for x in data]
    volumenes = [float(x[5]) for x in data]
    return cierres, altos, bajos, volumenes

def ema(cierres, n):
    k = 2 / (n + 1)
    e = cierres[0]
    for c in cierres[1:]:
        e = c * k + e * (1 - k)
    return e

def rsi(cierres, n=14):
    ganancias, perdidas = [], []
    for i in range(1, len(cierres)):
        diff = cierres[i] - cierres[i-1]
        ganancias.append(max(diff, 0))
        perdidas.append(max(-diff, 0))
    if len(ganancias) < n:
        return 50
    ag = sum(ganancias[-n:]) / n
    ap = sum(perdidas[-n:]) / n
    if ap == 0:
        return 100
    return 100 - (100 / (1 + ag / ap))

def atr(altos, bajos, cierres, n=14):
    trs = []
    for i in range(1, len(cierres)):
        tr = max(altos[i] - bajos[i],
                 abs(altos[i] - cierres[i-1]),
                 abs(bajos[i] - cierres[i-1]))
        trs.append(tr)
    return sum(trs[-n:]) / n if len(trs) >= n else sum(trs) / len(trs)

def tendencia_ema(cierres):
    e8  = ema(cierres[-20:], 8)
    e21 = ema(cierres[-30:], 21)
    return e8 > e21  # ⚡ Solo 2 EMAs (más permisivo)

def volumen_creciente(volumenes):
    vol_reciente = sum(volumenes[-3:]) / 3
    vol_base     = sum(volumenes[-10:-3]) / 7
    return vol_reciente > vol_base * 1.1  # ⚡ Bajado de 1.3 a 1.1

def score_agresivo(cierres, altos, bajos, volumenes):
    s = 0
    razones = []

    r = rsi(cierres)
    if 45 < r < 75:        # ⚡ Rango más amplio
        s += 2
        razones.append(f"RSI {r:.0f}✅")

    if tendencia_ema(cierres):
        s += 2
        razones.append("EMA✅")

    if volumen_creciente(volumenes):
        s += 2
        razones.append("Vol✅")

    momento = (cierres[-1] - cierres[-4]) / cierres[-4]
    if momento > 0.001:    # ⚡ Bajado de 0.002
        s += 2
        razones.append("Momento✅")

    if cierres[-1] > cierres[-2] > cierres[-3]:
        s += 1
        razones.append("Impulso✅")

    # ⚡ Nuevo: vela con cuerpo fuerte (señal de fuerza real)
    cuerpo = abs(cierres[-1] - cierres[-2])
    rango  = altos[-1] - bajos[-1]
    if rango > 0 and cuerpo / rango > 0.6:
        s += 1
        razones.append("VelaFuerte✅")

    return s, razones

# ================= LOOP =================
while True:
    try:

        # ================= GESTIÓN POSICIÓN =================
        if estado:
            cierres, altos, bajos, volumenes = get_klines(symbol_activo, "1m", 20)
            precio  = cierres[-1]
            atr_val = atr(altos, bajos, cierres)

            if precio > max_precio:
                max_precio = precio

            ganancia     = precio - entrada
            ganancia_pct = (ganancia / entrada) * 100

            # ⚡ SL más ajustado, TP más cercano = más hits
            sl = entrada - atr_val * 1.0
            tp = entrada + atr_val * 2.0

            trailing_activado = (max_precio - entrada) > atr_val * 0.8
            trailing_sl       = max_precio - atr_val * 0.6

            if precio <= sl:
                operaciones_totales += 1
                racha_perdidas += 1
                enviar_alerta(
                    f"🛑 <b>SL {symbol_activo}</b>\n"
                    f"P&amp;L: {ganancia_pct:.2f}%\n"
                    f"Stats: {operaciones_ganadoras}/{operaciones_totales}"
                )
                estado = False

            elif precio >= tp:
                operaciones_totales += 1
                operaciones_ganadoras += 1
                ganancia_acumulada += ganancia
                racha_perdidas = 0
                enviar_alerta(
                    f"💰 <b>TP {symbol_activo}</b>\n"
                    f"P&amp;L: +{ganancia_pct:.2f}%\n"
                    f"Acumulado: +{ganancia_acumulada:.4f}"
                )
                estado = False

            elif trailing_activado and precio <= trailing_sl:
                operaciones_totales += 1
                operaciones_ganadoras += 1
                ganancia_acumulada += ganancia
                racha_perdidas = 0
                enviar_alerta(
                    f"✅ <b>TRAILING {symbol_activo}</b>\n"
                    f"P&amp;L: +{ganancia_pct:.2f}%"
                )
                estado = False

            elif rsi(cierres) > 82:
                operaciones_totales += 1
                if ganancia > 0: operaciones_ganadoras += 1
                ganancia_acumulada += ganancia
                enviar_alerta(f"⚠️ <b>SALIDA RSI</b> {symbol_activo}\n{ganancia_pct:.2f}%")
                estado = False

            time.sleep(3)  # ⚡ Más rápido
            continue

        # ================= PROTECCIONES (más permisivas) =================
        if ganancia_acumulada >= 15:
            enviar_alerta("🛑 <b>META ALCANZADA</b> — Pausa 2min")
            time.sleep(120)
            ganancia_acumulada = 0
            continue

        if racha_perdidas >= 4:  # ⚡ Tolerancia de 4 (antes 3)
            enviar_alerta("⛔ <b>4 PÉRDIDAS SEGUIDAS</b> — Pausa 3min")
            time.sleep(180)
            racha_perdidas = 0
            continue

        # ================= FILTRO BTC (más permisivo) =================
        btc_1m, _, _, _ = get_klines("BTCUSDT", "1m", 50)
        btc_5m, _, _, _ = get_klines("BTCUSDT", "5m", 50)

        btc_rsi = rsi(btc_1m)

        # ⚡ Solo 2 timeframes y RSI hasta 78
        if not (tendencia_ema(btc_1m) and tendencia_ema(btc_5m)) or btc_rsi > 78:
            time.sleep(5)
            continue

        # ================= SCAN =================
        mejor = None
        mejor_score = 0
        mejor_razones = []

        for symbol in symbols:
            if symbol == "BTCUSDT":
                continue

            cierres, altos, bajos, volumenes = get_klines(symbol, "1m", 50)
            precio  = cierres[-1]
            atr_val = atr(altos, bajos, cierres)

            r = rsi(cierres)
            if r < 40 or r > 75:  # ⚡ Más amplio
                continue

            if not tendencia_ema(cierres):
                continue

            s, razones = score_agresivo(cierres, altos, bajos, volumenes)

            sl_est = precio - atr_val * 1.0
            riesgo = precio - sl_est
            if riesgo <= 0 or riesgo > atr_val * 2.5:
                continue

            if s > mejor_score:
                mejor_score = s
                mejor = (symbol, precio, cierres, altos, bajos, atr_val)
                mejor_razones = razones

        # ================= ENTRADA (score más bajo) =================
        if mejor and mejor_score >= 6:  # ⚡ Bajado de 9 a 6
            symbol_temp, precio_temp, cierres_temp, altos_temp, bajos_temp, atr_val = mejor

            sl = precio_temp - atr_val * 1.0
            tp = precio_temp + atr_val * 2.0
            riesgo_pct = ((precio_temp - sl) / precio_temp) * 100

            symbol_activo = symbol_temp
            entrada       = precio_temp
            max_precio    = entrada
            estado        = True

            enviar_alerta(
                f"⚡ <b>ENTRY {symbol_activo}</b>\n"
                f"Precio: {entrada:.4f}\n"
                f"SL: {sl:.4f} (-{riesgo_pct:.2f}%)\n"
                f"TP: {tp:.4f}\n"
                f"Score: {mejor_score}/10\n"
                f"Señales: {' | '.join(mejor_razones)}"
            )

        time.sleep(5)

    except Exception as e:
        print(f"Error: {e}")
        time.sleep(8)
