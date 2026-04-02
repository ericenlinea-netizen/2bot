
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

# ================= CONFIG =================
# Solo pares con alto volumen y liquidez real
symbols = ["ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT"]

FEE = 0.001          # 0.1% por operación (entrada + salida = 0.2%)
MIN_RR = 2.5         # Ratio riesgo/recompensa mínimo exigido
MIN_MOVIMIENTO = 0.006  # Mínimo 0.6% de recorrido esperado (cubre fees + ganancia real)
MAX_RIESGO_PCT = 0.015  # SL máximo 1.5% desde entrada

estado = False
entrada = 0
max_precio = 0
symbol_activo = None
atr_entrada = 0

racha_perdidas = 0
ganancia_acumulada_pct = 0
operaciones_totales = 0
operaciones_ganadoras = 0

enviar_alerta("📊 <b>BOT CONSERVADOR ANTI-SCALPING ACTIVO</b>\nSolo entradas de calidad con RR ≥ 2.5")

# ================= DATOS =================
def get_klines(symbol, interval, limit=100):
    try:
        data = requests.get(
            f"https://api.binance.com/api/v3/klines?symbol={symbol}&interval={interval}&limit={limit}",
            timeout=5
        ).json()
        if not isinstance(data, list):
            return None, None, None, None
        cierres   = [float(x[4]) for x in data]
        altos     = [float(x[2]) for x in data]
        bajos     = [float(x[3]) for x in data]
        volumenes = [float(x[5]) for x in data]
        return cierres, altos, bajos, volumenes
    except:
        return None, None, None, None

# ================= INDICADORES =================
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
        tr = max(
            altos[i] - bajos[i],
            abs(altos[i] - cierres[i-1]),
            abs(bajos[i] - cierres[i-1])
        )
        trs.append(tr)
    return sum(trs[-n:]) / n if trs else 0

def tendencia_solida(cierres):
    """EMA 8 > EMA 21 > EMA 55 — tendencia en 3 niveles"""
    e8  = ema(cierres[-30:], 8)
    e21 = ema(cierres[-50:], 21)
    e55 = ema(cierres, 55)
    return e8 > e21 > e55

def estructura_alcista(cierres):
    """
    Mínimos y máximos crecientes en los últimos 10 cierres.
    Valida que el mercado tiene estructura real, no ruido.
    """
    minimos  = [min(cierres[i-3:i]) for i in range(3, 11)]
    maximos  = [max(cierres[i-3:i]) for i in range(3, 11)]
    min_crece = all(minimos[i] <= minimos[i+1] for i in range(len(minimos)-1))
    max_crece = all(maximos[i] <= maximos[i+1] for i in range(len(maximos)-1))
    return min_crece and max_crece

def pullback_limpio(cierres, altos, bajos, atr_val):
    """
    Pullback en zona de soporte:
    - Retroceso de 2-5 velas hacia la EMA21
    - No rompe mínimo estructural
    - Vela de cierre fuerte hacia arriba
    """
    e21        = ema(cierres[-30:], 21)
    precio     = cierres[-1]
    minimo_rec = min(bajos[-5:])

    # El precio está cerca de EMA21 (zona de rebote esperada)
    cerca_ema  = abs(precio - e21) / e21 < 0.005

    # El pullback no destruyó la estructura (no cayó > 1 ATR por debajo de EMA21)
    estructura_ok = minimo_rec > e21 - atr_val

    # Vela actual cierra alcista con cuerpo > 50% del rango
    cuerpo = cierres[-1] - bajos[-1]
    rango  = altos[-1] - bajos[-1]
    vela_fuerte = rango > 0 and (cuerpo / rango) > 0.55 and cierres[-1] > cierres[-2]

    return cerca_ema and estructura_ok and vela_fuerte

def volumen_confirma(volumenes):
    """Volumen actual > 150% del promedio de las últimas 20 velas"""
    promedio = sum(volumenes[-20:-1]) / 19
    return volumenes[-1] > promedio * 1.5

def rsi_en_zona(cierres):
    """RSI entre 52 y 65 — momentum positivo sin sobrecompra"""
    r = rsi(cierres)
    return 52 <= r <= 65, r

def movimiento_suficiente(precio, sl, tp):
    """
    Verifica que el trade cubra fees reales (0.2% r/t) y tenga ganancia real mínima.
    TP debe ser al menos MIN_MOVIMIENTO desde entrada.
    """
    recorrido_tp = (tp - precio) / precio
    recorrido_sl = (precio - sl) / precio
    rr           = recorrido_tp / recorrido_sl if recorrido_sl > 0 else 0
    return recorrido_tp >= MIN_MOVIMIENTO and rr >= MIN_RR

# ================= SCORE COMPLETO =================
def evaluar_entrada(symbol, cierres_5m, altos_5m, bajos_5m, volumenes_5m,
                              cierres_15m, altos_15m, bajos_15m):
    precio  = cierres_5m[-1]
    atr_5m  = atr(altos_5m, bajos_5m, cierres_5m)
    atr_15m = atr(altos_15m, bajos_15m, cierres_15m)

    score   = 0
    razones = []
    rechazos = []

    # --- FILTROS OBLIGATORIOS (cualquiera rechaza la entrada) ---

    if not tendencia_solida(cierres_15m):
        rechazos.append("No tendencia en 15m")
        return 0, [], rechazos, None, None

    if not tendencia_solida(cierres_5m):
        rechazos.append("No tendencia en 5m")
        return 0, [], rechazos, None, None

    if not estructura_alcista(cierres_15m):
        rechazos.append("Estructura 15m rota")
        return 0, [], rechazos, None, None

    rsi_ok, rsi_val = rsi_en_zona(cierres_5m)
    if not rsi_ok:
        rechazos.append(f"RSI fuera de zona ({rsi_val:.0f})")
        return 0, [], rechazos, None, None

    if not volumen_confirma(volumenes_5m):
        rechazos.append("Volumen insuficiente")
        return 0, [], rechazos, None, None

    # --- CÁLCULO DE NIVELES (basado en ATR real) ---
    sl = precio - atr_5m * 1.2
    tp = precio + atr_5m * 3.0

    # Asegura que el riesgo no supere el máximo permitido
    if (precio - sl) / precio > MAX_RIESGO_PCT:
        sl = precio * (1 - MAX_RIESGO_PCT)

    if not movimiento_suficiente(precio, sl, tp):
        rechazos.append(f"Movimiento insuficiente — TP:{((tp-precio)/precio*100):.2f}%")
        return 0, [], rechazos, None, None

    # --- PUNTUACIÓN (señales adicionales de calidad) ---

    if pullback_limpio(cierres_5m, altos_5m, bajos_5m, atr_5m):
        score += 3
        razones.append("Pullback✅")

    # Confirmación en 15m también en pullback
    if pullback_limpio(cierres_15m, altos_15m, bajos_15m, atr_15m):
        score += 2
        razones.append("Pullback15m✅")

    # Momento en últimas 6 velas
    momento = (cierres_5m[-1] - cierres_5m[-6]) / cierres_5m[-6]
    if momento > 0.003:
        score += 2
        razones.append(f"Momento +{momento*100:.2f}%✅")

    # RSI ideal (zona óptima de entrada)
    if 55 <= rsi_val <= 62:
        score += 1
        razones.append(f"RSI óptimo ({rsi_val:.0f})✅")
    else:
        razones.append(f"RSI {rsi_val:.0f}✅")

    # Vela de confirmación fuerte
    cuerpo = cierres_5m[-1] - bajos_5m[-1]
    rango  = altos_5m[-1] - bajos_5m[-1]
    if rango > 0 and (cuerpo / rango) > 0.7:
        score += 1
        razones.append("Vela fuerte✅")

    # ATR con volatilidad suficiente para operar
    if atr_5m / precio > 0.002:
        score += 1
        razones.append("Volatilidad✅")

    return score, razones, rechazos, sl, tp

# ================= LOOP PRINCIPAL =================
while True:
    try:

        # ================= GESTIÓN POSICIÓN ABIERTA =================
        if estado:
            cierres, altos, bajos, vols = get_klines(symbol_activo, "5m", 30)
            if cierres is None:
                time.sleep(10)
                continue

            precio  = cierres[-1]
            atr_val = atr(altos, bajos, cierres)

            if precio > max_precio:
                max_precio = precio

            ganancia_pct = ((precio - entrada) / entrada) * 100

            sl = entrada - atr_entrada * 1.2
            if (entrada - sl) / entrada > MAX_RIESGO_PCT:
                sl = entrada * (1 - MAX_RIESGO_PCT)

            tp           = entrada + atr_entrada * 3.0
            trailing_sl  = max_precio - atr_val * 1.0

            # SL tocado
            if precio <= sl:
                operaciones_totales += 1
                racha_perdidas += 1
                pnl_real = ganancia_pct - (FEE * 2 * 100)
                enviar_alerta(
                    f"🛑 <b>SL — {symbol_activo}</b>\n"
                    f"Entrada: {entrada:.4f} → {precio:.4f}\n"
                    f"P&amp;L real: {pnl_real:.2f}%\n"
                    f"Ops: {operaciones_ganadoras}/{operaciones_totales}"
                )
                estado = False

            # TP tocado
            elif precio >= tp:
                operaciones_totales += 1
                operaciones_ganadoras += 1
                racha_perdidas = 0
                pnl_real = ganancia_pct - (FEE * 2 * 100)
                ganancia_acumulada_pct += pnl_real
                enviar_alerta(
                    f"💰 <b>TP — {symbol_activo}</b>\n"
                    f"Entrada: {entrada:.4f} → {precio:.4f}\n"
                    f"P&amp;L real: +{pnl_real:.2f}%\n"
                    f"Acumulado: +{ganancia_acumulada_pct:.2f}%\n"
                    f"Ops: {operaciones_ganadoras}/{operaciones_totales}"
                )
                estado = False

            # Trailing stop (solo activo si hay ganancia > 1 ATR)
            elif (max_precio - entrada) > atr_val and precio <= trailing_sl:
                operaciones_totales += 1
                operaciones_ganadoras += 1
                racha_perdidas = 0
                pnl_real = ganancia_pct - (FEE * 2 * 100)
                ganancia_acumulada_pct += pnl_real
                enviar_alerta(
                    f"✅ <b>TRAILING — {symbol_activo}</b>\n"
                    f"Entrada: {entrada:.4f} → {precio:.4f}\n"
                    f"P&amp;L real: +{pnl_real:.2f}%"
                )
                estado = False

            # Salida de emergencia: RSI sobrecomprado extremo
            elif rsi(cierres) > 80:
                operaciones_totales += 1
                if ganancia_pct > 0:
                    operaciones_ganadoras += 1
                pnl_real = ganancia_pct - (FEE * 2 * 100)
                ganancia_acumulada_pct += pnl_real
                enviar_alerta(
                    f"⚠️ <b>SALIDA RSI — {symbol_activo}</b>\n"
                    f"RSI extremo, salida preventiva\n"
                    f"P&amp;L real: {pnl_real:.2f}%"
                )
                estado = False

            time.sleep(15)  # Revisión cada 15s (no scalping)
            continue

        # ================= PROTECCIONES =================
        if ganancia_acumulada_pct >= 3.0:
            enviar_alerta(
                f"🏆 <b>META DIARIA ALCANZADA</b>\n"
                f"+{ganancia_acumulada_pct:.2f}% acumulado\n"
                f"Pausando 30 minutos para proteger ganancias..."
            )
            time.sleep(1800)
            ganancia_acumulada_pct = 0
            continue

        if racha_perdidas >= 2:
            enviar_alerta(
                f"⛔ <b>2 PÉRDIDAS SEGUIDAS</b>\n"
                f"Pausando 20 minutos para revisar mercado..."
            )
            time.sleep(1200)
            racha_perdidas = 0
            continue

        # ================= FILTRO MACRO BTC =================
        btc_5m,  _, _,  _ = get_klines("BTCUSDT", "5m",  100)
        btc_15m, _, btc_15m_bajos, _ = get_klines("BTCUSDT", "15m", 100)
        btc_1h,  _, _,  _ = get_klines("BTCUSDT", "1h",  100)

        if btc_5m is None or btc_15m is None or btc_1h is None:
            time.sleep(15)
            continue

        # BTC debe estar en tendencia en los 3 timeframes
        btc_ok = (
            tendencia_solida(btc_5m) and
            tendencia_solida(btc_15m) and
            tendencia_solida(btc_1h)
        )

        btc_rsi = rsi(btc_5m)

        if not btc_ok:
            print("BTC sin tendencia — esperando...")
            time.sleep(30)
            continue

        if btc_rsi > 72:
            print(f"BTC sobrecomprado (RSI {btc_rsi:.0f}) — esperando...")
            time.sleep(30)
            continue

        # ================= SCAN DE PARES =================
        mejor        = None
        mejor_score  = 0
        mejor_datos  = {}

        for symbol in symbols:
            c5, a5, b5, v5 = get_klines(symbol, "5m", 100)
            c15, a15, b15, v15 = get_klines(symbol, "15m", 100)

            if c5 is None or c15 is None:
                continue

            precio = c5[-1]

            score, razones, rechazos, sl, tp = evaluar_entrada(
                symbol, c5, a5, b5, v5, c15, a15, b15
            )

            if score > mejor_score:
                mejor_score = score
                mejor = symbol
                mejor_datos = {
                    "precio": precio,
                    "sl": sl,
                    "tp": tp,
                    "razones": razones,
                    "atr": atr(a5, b5, c5)
                }

        # ================= ENTRADA (score mínimo 6/10) =================
        if mejor and mejor_score >= 6:
            d          = mejor_datos
            precio     = d["precio"]
            sl         = d["sl"]
            tp         = d["tp"]
            riesgo_pct = ((precio - sl) / precio) * 100
            reward_pct = ((tp - precio) / precio) * 100
            rr         = reward_pct / riesgo_pct
            pnl_real_esperado = reward_pct - (FEE * 2 * 100)

            symbol_activo = mejor
            entrada       = precio
            max_precio    = precio
            atr_entrada   = d["atr"]
            estado        = True

            enviar_alerta(
                f"🚀 <b>ENTRY — {symbol_activo}</b>\n"
                f"Precio: {entrada:.4f}\n"
                f"SL: {sl:.4f} (-{riesgo_pct:.2f}%)\n"
                f"TP: {tp:.4f} (+{reward_pct:.2f}%)\n"
                f"RR: 1:{rr:.1f}\n"
                f"P&amp;L esperado (neto): +{pnl_real_esperado:.2f}%\n"
                f"Score: {mejor_score}/10\n"
                f"Señales: {' | '.join(d['razones'])}"
            )
        else:
            print(f"Sin señal válida. Mejor score: {mejor_score}/10")

        time.sleep(30)  # Scan cada 30 segundos (no cada 5s)

    except Exception as e:
        print(f"Error: {e}")
        time.sleep(20)
