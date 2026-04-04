import os
import requests
import time
from datetime import datetime, date

# ================= TELEGRAM =================
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "8329327841:AAE_oEg3pFrmVL3SAjiHe_VaU8AuoL5xdL0")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "5019372975")


def enviar_alerta(msg):
    if not TOKEN or not CHAT_ID or "PON_AQUI" in TOKEN or "PON_AQUI" in CHAT_ID:
        print("Telegram no configurado:\n", msg)
        return

    try:
        requests.post(
            f"https://api.telegram.org/bot{TOKEN}/sendMessage",
            data={"chat_id": CHAT_ID, "text": msg, "parse_mode": "HTML"},
            timeout=10
        )
    except Exception as e:
        print("Error enviando alerta:", e)


# ================= CONFIG =================
symbols = ["BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "ADAUSDT", "XRPUSDT"]

estado = False
entrada = 0.0
max_precio = 0.0
symbol_activo = None
sl_actual = 0.0
tp_actual = 0.0
hora_entrada = None
score_entrada = 0

# ===== PARAMETROS ESTRATEGIA =====
score_minimo_entrada = 9

# ===== PARAMETROS DE TRADING REAL =====
capital_inicial = 1000.0
margen_por_trade = 10.0
apalancamiento = 10.0
notional_por_trade = margen_por_trade * apalancamiento
fee_rate = 0.0004  # 0.04% por lado; ajusta según exchange
usar_fees = True

# ===== RISK MANAGER =====
riesgo_por_trade = 0.01
drawdown_max = -0.05 * capital_inicial
cooldown_symbol = {}

# ===== STATS GENERALES =====
ganancia_total = 0.0
operaciones = 0
ganadoras = 0
racha_perdidas = 0
racha_ganadoras = 0
mejor_ganancia = None
peor_perdida = None
ultima_operacion = None

# ===== STATS DIARIOS =====
fecha_actual_stats = date.today()
ganancia_dia = 0.0
operaciones_dia = 0
ganadoras_dia = 0

# ===== STATS POR SIMBOLO =====
stats_symbol = {
    s: {
        "trades": 0,
        "wins": 0,
        "pnl": 0.0,
        "best": None,
        "worst": None,
    }
    for s in symbols
}

# ===== REPORTES =====
ultimo_reporte = 0
intervalo_reporte = 1800  # 30 min

# ===== DEBUG SUAVE =====
ultimo_debug = 0
intervalo_debug = 900  # 15 min


# ================= HELPERS =================
def ahora():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def fmt_price(n):
    return f"{n:.4f}"


def fmt_money(n):
    signo = "+" if n >= 0 else ""
    return f"{signo}{n:.2f} USD"


def fmt_pct(n):
    signo = "+" if n >= 0 else ""
    return f"{signo}{n:.2f}%"


def capital_actual():
    return capital_inicial + ganancia_total


def perdedoras():
    return operaciones - ganadoras


def perdedoras_dia():
    return operaciones_dia - ganadoras_dia


def winrate():
    return (ganadoras / operaciones * 100) if operaciones > 0 else 0.0


def winrate_dia():
    return (ganadoras_dia / operaciones_dia * 100) if operaciones_dia > 0 else 0.0


def duracion_trade():
    if not hora_entrada:
        return "-"
    delta = datetime.now() - hora_entrada
    minutos = int(delta.total_seconds() // 60)
    segundos = int(delta.total_seconds() % 60)
    return f"{minutos}m {segundos}s"


def precio_a_pct(precio_entrada, precio_actual):
    if precio_entrada <= 0:
        return 0.0
    return ((precio_actual - precio_entrada) / precio_entrada) * 100


def calcular_fees():
    if not usar_fees:
        return 0.0
    return notional_por_trade * fee_rate * 2


def calcular_pnl_usd(precio_entrada, precio_salida):
    if precio_entrada <= 0:
        return 0.0, 0.0, 0.0

    variacion_pct = (precio_salida - precio_entrada) / precio_entrada
    pnl_bruto = variacion_pct * notional_por_trade
    fees = calcular_fees()
    pnl_neto = pnl_bruto - fees
    pnl_pct_trade = (pnl_neto / margen_por_trade) * 100 if margen_por_trade > 0 else 0.0

    return pnl_neto, pnl_pct_trade, fees


def pnl_actual_trade(precio):
    if not estado:
        return 0.0, 0.0
    pnl, pnl_pct_trade, _ = calcular_pnl_usd(entrada, precio)
    return pnl, pnl_pct_trade


def riesgo_actual():
    if entrada <= 0 or sl_actual <= 0:
        return 0.0, 0.0, 0.0
    riesgo_pct_precio = ((entrada - sl_actual) / entrada) * 100
    riesgo_usd = (riesgo_pct_precio / 100) * notional_por_trade
    if usar_fees:
        riesgo_usd += calcular_fees()
    riesgo_pct_margen = (riesgo_usd / margen_por_trade) * 100 if margen_por_trade > 0 else 0.0
    return riesgo_usd, riesgo_pct_precio, riesgo_pct_margen


def beneficio_objetivo():
    if entrada <= 0 or tp_actual <= 0:
        return 0.0, 0.0, 0.0
    beneficio_pct_precio = ((tp_actual - entrada) / entrada) * 100
    beneficio_usd = (beneficio_pct_precio / 100) * notional_por_trade
    if usar_fees:
        beneficio_usd -= calcular_fees()
    beneficio_pct_margen = (beneficio_usd / margen_por_trade) * 100 if margen_por_trade > 0 else 0.0
    return beneficio_usd, beneficio_pct_precio, beneficio_pct_margen


def actualizar_extremos_trade(pnl):
    global mejor_ganancia, peor_perdida
    if mejor_ganancia is None or pnl > mejor_ganancia:
        mejor_ganancia = pnl
    if peor_perdida is None or pnl < peor_perdida:
        peor_perdida = pnl


def revisar_reset_diario():
    global fecha_actual_stats, ganancia_dia, operaciones_dia, ganadoras_dia
    hoy = date.today()
    if hoy != fecha_actual_stats:
        fecha_actual_stats = hoy
        ganancia_dia = 0.0
        operaciones_dia = 0
        ganadoras_dia = 0


def registrar_trade(symbol, pnl, fue_ganadora, tipo):
    global operaciones, ganadoras, ganancia_total
    global operaciones_dia, ganadoras_dia, ganancia_dia
    global racha_perdidas, racha_ganadoras, ultima_operacion

    revisar_reset_diario()

    operaciones += 1
    operaciones_dia += 1
    ganancia_total += pnl
    ganancia_dia += pnl
    ultima_operacion = tipo

    if fue_ganadora:
        ganadoras += 1
        ganadoras_dia += 1
        racha_ganadoras += 1
        racha_perdidas = 0
    else:
        racha_perdidas += 1
        racha_ganadoras = 0

    actualizar_extremos_trade(pnl)

    ss = stats_symbol[symbol]
    ss["trades"] += 1
    ss["pnl"] += pnl
    if fue_ganadora:
        ss["wins"] += 1
    if ss["best"] is None or pnl > ss["best"]:
        ss["best"] = pnl
    if ss["worst"] is None or pnl < ss["worst"]:
        ss["worst"] = pnl


def resumen_symbol(symbol):
    ss = stats_symbol[symbol]
    wr = (ss["wins"] / ss["trades"] * 100) if ss["trades"] > 0 else 0.0
    return (
        f"🪙 <b>{symbol}</b>\n"
        f"Trades: {ss['trades']} | Winrate: {wr:.1f}% | PnL: {fmt_money(ss['pnl'])}"
    )


def top_symbols_msg():
    ranking = sorted(stats_symbol.items(), key=lambda x: x[1]["pnl"], reverse=True)
    lineas = []
    for symbol, ss in ranking[:3]:
        wr = (ss["wins"] / ss["trades"] * 100) if ss["trades"] > 0 else 0.0
        lineas.append(f"• <b>{symbol}</b>: {fmt_money(ss['pnl'])} | {ss['trades']} trades | WR {wr:.1f}%")
    return "\n".join(lineas) if lineas else "Sin datos"


def resumen_general():
    return (
        f"📊 <b>ESTADO GENERAL</b>\n"
        f"💰 <b>PnL total:</b> {fmt_money(ganancia_total)}\n"
        f"🏦 <b>Capital estimado:</b> {fmt_money(capital_actual())}\n"
        f"📈 <b>Trades:</b> {operaciones}\n"
        f"🏆 <b>Ganadoras:</b> {ganadoras}\n"
        f"❌ <b>Perdedoras:</b> {perdedoras()}\n"
        f"🎯 <b>Winrate:</b> {winrate():.1f}%\n"
        f"🔥 <b>Racha ganadoras:</b> {racha_ganadoras}\n"
        f"📉 <b>Racha pérdidas:</b> {racha_perdidas}\n"
        f"🚀 <b>Mejor trade:</b> {fmt_money(mejor_ganancia) if mejor_ganancia is not None else 'N/A'}\n"
        f"🩸 <b>Peor trade:</b> {fmt_money(peor_perdida) if peor_perdida is not None else 'N/A'}\n"
        f"🧾 <b>Último cierre:</b> {ultima_operacion if ultima_operacion else 'N/A'}"
    )


def resumen_diario():
    return (
        f"📅 <b>RESUMEN DEL DÍA</b>\n"
        f"💰 <b>PnL día:</b> {fmt_money(ganancia_dia)}\n"
        f"📈 <b>Trades día:</b> {operaciones_dia}\n"
        f"🏆 <b>Ganadoras día:</b> {ganadoras_dia}\n"
        f"❌ <b>Perdedoras día:</b> {perdedoras_dia()}\n"
        f"🎯 <b>Winrate día:</b> {winrate_dia():.1f}%"
    )


def panel_trade_activo(precio_actual=None):
    if not estado or not symbol_activo:
        return "⚪ <b>Trade activo:</b> Ninguno"

    if precio_actual is None:
        precio_actual = entrada

    pnl, pnl_pct_trade = pnl_actual_trade(precio_actual)
    riesgo_usd, riesgo_pct_precio, riesgo_pct_margen = riesgo_actual()
    beneficio_usd, beneficio_pct_precio, beneficio_pct_margen = beneficio_objetivo()

    return (
        f"🟢 <b>TRADE ACTIVO</b>\n"
        f"🪙 <b>Activo:</b> {symbol_activo}\n"
        f"💵 <b>Entrada:</b> {fmt_price(entrada)}\n"
        f"📍 <b>Precio actual:</b> {fmt_price(precio_actual)}\n"
        f"📈 <b>PnL flotante:</b> {fmt_money(pnl)} ({fmt_pct(pnl_pct_trade)})\n"
        f"🛡 <b>SL:</b> {fmt_price(sl_actual)} | Riesgo aprox: {fmt_money(-riesgo_usd)} ({fmt_pct(-riesgo_pct_margen)})\n"
        f"🎯 <b>TP:</b> {fmt_price(tp_actual)} | Objetivo aprox: {fmt_money(beneficio_usd)} ({fmt_pct(beneficio_pct_margen)})\n"
        f"⬆️ <b>Máximo:</b> {fmt_price(max_precio)}\n"
        f"📊 <b>Score entrada:</b> {score_entrada}\n"
        f"⏱ <b>Duración:</b> {duracion_trade()}"
    )


def msg_inicio():
    return (
        f"🏦 <b>BOT RISK MANAGER ACTIVO</b>\n\n"
        f"🕒 <b>Inicio:</b> {ahora()}\n"
        f"💼 <b>Capital inicial:</b> {fmt_money(capital_inicial)}\n"
        f"💸 <b>Margen por trade:</b> {fmt_money(margen_por_trade)}\n"
        f"⚡ <b>Apalancamiento:</b> {apalancamiento:.1f}x\n"
        f"📦 <b>Notional:</b> {fmt_money(notional_por_trade)}\n"
        f"🧾 <b>Fees activas:</b> {'Sí' if usar_fees else 'No'}\n"
        f"🛑 <b>Drawdown máx:</b> {fmt_money(drawdown_max)}\n"
        f"🎯 <b>Score mínimo entrada:</b> {score_minimo_entrada}\n"
        f"🪙 <b>Símbolos:</b> {', '.join(symbols)}"
    )


def msg_entry(symbol, precio_entrada, sl, tp, score_val):
    riesgo_usd, _, riesgo_pct_margen = riesgo_actual()
    beneficio_usd, _, beneficio_pct_margen = beneficio_objetivo()

    return (
        f"🚀 <b>NUEVA ENTRADA</b>\n\n"
        f"🪙 <b>Activo:</b> {symbol}\n"
        f"💵 <b>Entrada:</b> {fmt_price(precio_entrada)}\n"
        f"🛡 <b>SL:</b> {fmt_price(sl)} | Riesgo aprox: {fmt_money(-riesgo_usd)} ({fmt_pct(-riesgo_pct_margen)})\n"
        f"🎯 <b>TP:</b> {fmt_price(tp)} | Objetivo aprox: {fmt_money(beneficio_usd)} ({fmt_pct(beneficio_pct_margen)})\n"
        f"📈 <b>Score:</b> {score_val}\n"
        f"🕒 <b>Hora:</b> {ahora()}\n\n"
        f"{resumen_general()}\n\n"
        f"{resumen_diario()}\n\n"
        f"{resumen_symbol(symbol)}"
    )


def msg_close(tipo, symbol, precio_entrada, precio_salida, pnl_usd, pnl_pct_trade, fees):
    emoji = "💰" if pnl_usd >= 0 else "🛑"
    movimiento_precio_pct = precio_a_pct(precio_entrada, precio_salida)

    return (
        f"{emoji} <b>{tipo}</b>\n\n"
        f"🪙 <b>Activo:</b> {symbol}\n"
        f"💵 <b>Entrada:</b> {fmt_price(precio_entrada)}\n"
        f"💸 <b>Salida:</b> {fmt_price(precio_salida)}\n"
        f"📊 <b>Movimiento precio:</b> {fmt_pct(movimiento_precio_pct)}\n"
        f"💰 <b>PnL trade:</b> {fmt_money(pnl_usd)} ({fmt_pct(pnl_pct_trade)})\n"
        f"🧾 <b>Fees estimadas:</b> {fmt_money(-fees if fees else 0.0)}\n"
        f"⏱ <b>Duración:</b> {duracion_trade()}\n"
        f"🕒 <b>Cierre:</b> {ahora()}\n\n"
        f"{resumen_general()}\n\n"
        f"{resumen_diario()}\n\n"
        f"{resumen_symbol(symbol)}"
    )


def msg_pausa():
    return (
        f"⛔ <b>PAUSA POR MAL RENDIMIENTO</b>\n\n"
        f"📉 <b>Racha de pérdidas:</b> {racha_perdidas}\n"
        f"🕒 <b>Hora:</b> {ahora()}\n\n"
        f"{resumen_general()}\n\n"
        f"{resumen_diario()}"
    )


def msg_drawdown():
    return (
        f"🛑 <b>STOP GLOBAL POR DRAWDOWN</b>\n\n"
        f"💰 <b>PnL acumulado:</b> {fmt_money(ganancia_total)}\n"
        f"⚠️ <b>Límite drawdown:</b> {fmt_money(drawdown_max)}\n"
        f"🕒 <b>Hora:</b> {ahora()}\n\n"
        f"{resumen_general()}\n\n"
        f"{resumen_diario()}"
    )


def msg_resumen_periodico(precio_actual=None):
    return (
        f"🧾 <b>RESUMEN PERIÓDICO</b>\n\n"
        f"{panel_trade_activo(precio_actual)}\n\n"
        f"{resumen_general()}\n\n"
        f"{resumen_diario()}\n\n"
        f"🥇 <b>TOP SÍMBOLOS</b>\n"
        f"{top_symbols_msg()}\n\n"
        f"🕒 <b>Hora:</b> {ahora()}"
    )


def msg_debug(symbol, precio, s, faltantes):
    faltan_txt = ", ".join(faltantes[:4]) if faltantes else "ninguna"
    return (
        f"🔎 <b>DEBUG DE ESCANEO</b>\n\n"
        f"🪙 <b>Mejor símbolo:</b> {symbol}\n"
        f"💵 <b>Precio:</b> {fmt_price(precio)}\n"
        f"📈 <b>Score actual:</b> {s}\n"
        f"🎯 <b>Score requerido:</b> {score_minimo_entrada}\n"
        f"🧩 <b>Faltó:</b> {faltan_txt}\n"
        f"🕒 <b>Hora:</b> {ahora()}\n\n"
        f"{resumen_general()}\n\n"
        f"{resumen_diario()}"
    )


def msg_error(err):
    return (
        f"⚠️ <b>ERROR EN EJECUCIÓN</b>\n\n"
        f"<code>{str(err)[:300]}</code>\n"
        f"🕒 <b>Hora:</b> {ahora()}"
    )


# ================= DATA =================
def get_klines(symbol, interval, limit=50):
    r = requests.get(
        f"https://api.binance.com/api/v3/klines?symbol={symbol}&interval={interval}&limit={limit}",
        timeout=10
    )
    data = r.json()

    if not isinstance(data, list) or len(data) == 0:
        raise ValueError(f"Respuesta inválida de Binance para {symbol}: {data}")

    cierres = [float(x[4]) for x in data]
    altos = [float(x[2]) for x in data]
    bajos = [float(x[3]) for x in data]
    volumenes = [float(x[5]) for x in data]
    return cierres, altos, bajos, volumenes


def ema(valores, n):
    k = 2 / (n + 1)
    resultado = [valores[0]]
    for v in valores[1:]:
        resultado.append(v * k + resultado[-1] * (1 - k))
    return resultado


def atr(altos, bajos, cierres, n=14):
    trs = []
    for i in range(1, len(cierres)):
        tr = max(
            altos[i] - bajos[i],
            abs(altos[i] - cierres[i - 1]),
            abs(bajos[i] - cierres[i - 1])
        )
        trs.append(tr)
    return sum(trs[-n:]) / n if len(trs) >= n else cierres[-1] * 0.002


def detectar_pullback(c):
    return len(c) >= 5 and c[-5] < c[-4] < c[-3] and c[-3] > c[-2] and c[-1] > c[-2]


def volumen_alto(v):
    if len(v) < 20:
        return False
    promedio = sum(v[-20:-1]) / 19
    return v[-1] > promedio * 1.2


def razones_score(c, a, b, v, precio):
    ema_ok = ema(c, 9)[-1] > ema(c, 21)[-1]
    pullback_ok = detectar_pullback(c)
    vol_ok = volumen_alto(v)
    mom1_ok = (c[-1] - c[-2]) > (0.0004 * precio)
    mom2_ok = (c[-1] - c[-5]) > (0.0005 * precio)

    s = 0
    if ema_ok:
        s += 2
    if pullback_ok:
        s += 2
    if vol_ok:
        s += 3
    if mom1_ok:
        s += 2
    if mom2_ok:
        s += 1

    faltantes = []
    if not ema_ok:
        faltantes.append("EMA 9>21")
    if not pullback_ok:
        faltantes.append("pullback")
    if not vol_ok:
        faltantes.append("volumen alto")
    if not mom1_ok:
        faltantes.append("momentum corto")
    if not mom2_ok:
        faltantes.append("momentum extendido")

    return s, faltantes


def calcular_sl_tp(c, a, b, precio_entrada):
    atr_val = atr(a, b, c)

    sl = max(
        min(c[-5:]),
        precio_entrada - (1.5 * atr_val),
        precio_entrada - (0.0015 * precio_entrada)
    )

    riesgo = precio_entrada - sl
    tp = precio_entrada + riesgo * 2
    return sl, tp


# ================= INICIO =================
enviar_alerta(msg_inicio())

# ================= LOOP =================
while True:
    try:
        revisar_reset_diario()

        if ganancia_total <= drawdown_max:
            enviar_alerta(msg_drawdown())
            time.sleep(300)
            continue

        if estado:
            c, a, b, v = get_klines(symbol_activo, "1m", 20)
            precio = c[-1]

            if precio > max_precio:
                max_precio = precio

            if time.time() - ultimo_reporte > intervalo_reporte:
                enviar_alerta(msg_resumen_periodico(precio))
                ultimo_reporte = time.time()

            pnl_usd, pnl_pct_trade, fees = calcular_pnl_usd(entrada, precio)
            trailing = (max_precio - entrada) * 0.4

            if precio <= sl_actual:
                registrar_trade(symbol_activo, pnl_usd, False, "STOP LOSS")
                enviar_alerta(msg_close("STOP LOSS", symbol_activo, entrada, precio, pnl_usd, pnl_pct_trade, fees))
                cooldown_symbol[symbol_activo] = time.time()

                estado = False
                symbol_activo = None
                hora_entrada = None
                score_entrada = 0

            elif precio >= tp_actual:
                registrar_trade(symbol_activo, pnl_usd, True, "TAKE PROFIT")
                enviar_alerta(msg_close("TAKE PROFIT", symbol_activo, entrada, precio, pnl_usd, pnl_pct_trade, fees))
                cooldown_symbol[symbol_activo] = time.time()

                estado = False
                symbol_activo = None
                hora_entrada = None
                score_entrada = 0

            elif max_precio - precio >= trailing and pnl_usd > 0:
                registrar_trade(symbol_activo, pnl_usd, True, "TRAILING STOP")
                enviar_alerta(msg_close("TRAILING STOP", symbol_activo, entrada, precio, pnl_usd, pnl_pct_trade, fees))
                cooldown_symbol[symbol_activo] = time.time()

                estado = False
                symbol_activo = None
                hora_entrada = None
                score_entrada = 0

            time.sleep(5)
            continue

        if time.time() - ultimo_reporte > intervalo_reporte:
            enviar_alerta(msg_resumen_periodico())
            ultimo_reporte = time.time()

        if racha_perdidas >= 3:
            enviar_alerta(msg_pausa())
            time.sleep(120)
            racha_perdidas = 0
            continue

        mejor = None
        mejor_score = 0
        mejor_debug = None

        for symbol in symbols:
            if symbol in cooldown_symbol and time.time() - cooldown_symbol[symbol] < 30:
                continue

            c, a, b, v = get_klines(symbol, "1m", 50)
            precio = c[-1]

            if (c[-1] - c[-2]) / c[-2] > 0.002:
                continue

            if symbol == "BTCUSDT" and (c[-1] - c[-3]) / c[-3] > 0.003:
                continue

            s, faltantes = razones_score(c, a, b, v, precio)

            if s > mejor_score:
                mejor_score = s
                mejor = (symbol, precio, c, a, b)
                mejor_debug = (symbol, precio, s, faltantes)

        if (
            not estado
            and mejor_debug
            and time.time() - ultimo_debug > intervalo_debug
            and mejor_score < score_minimo_entrada
        ):
            enviar_alerta(msg_debug(mejor_debug[0], mejor_debug[1], mejor_debug[2], mejor_debug[3]))
            ultimo_debug = time.time()

        if mejor and mejor_score >= score_minimo_entrada:
            symbol_activo, entrada, c, a, b = mejor
            max_precio = entrada
            sl_actual, tp_actual = calcular_sl_tp(c, a, b, entrada)
            hora_entrada = datetime.now()
            score_entrada = mejor_score
            estado = True

            enviar_alerta(msg_entry(symbol_activo, entrada, sl_actual, tp_actual, mejor_score))

        time.sleep(5)

    except Exception as e:
        print("Error:", e)
        try:
            enviar_alerta(msg_error(e))
        except Exception:
            pass
        time.sleep(5)
