import requests
import time
import math
from datetime import datetime

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
symbols = ["BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "ADAUSDT", "XRPUSDT"]

estado = False
entrada = 0
max_precio = 0
symbol_activo = None

# ===== RISK MANAGER =====
capital = 1000
riesgo_por_trade = 0.01
drawdown_max = -0.05 * capital

cooldown_symbol = {}

# ===== STATS =====
ganancia_total = 0
operaciones = 0
ganadoras = 0
racha_perdidas = 0

enviar_alerta("🏦 <b>BOT RISK MANAGER ACTIVO</b>")

# ================= FUNCIONES =================

def get_klines(symbol, interval, limit=50):
    data = requests.get(
        f"https://api.binance.com/api/v3/klines?symbol={symbol}&interval={interval}&limit={limit}",
        timeout=10
    ).json()
    cierres = [float(x[4]) for x in data]
    altos   = [float(x[2]) for x in data]
    bajos   = [float(x[3]) for x in data]
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
            abs(altos[i] - cierres[i-1]),
            abs(bajos[i] - cierres[i-1])
        )
        trs.append(tr)
    return sum(trs[-n:]) / n if len(trs) >= n else cierres[-1]*0.002

def detectar_pullback(c):
    return c[-5] < c[-4] < c[-3] and c[-3] > c[-2] and c[-1] > c[-2]

def volumen_alto(v):
    return v[-1] > sum(v[-20:-1]) / 19 * 1.2

def score(c, a, b, v, precio):
    s = 0

    if ema(c,9)[-1] > ema(c,21)[-1]:
        s += 2
    if detectar_pullback(c):
        s += 2
    if volumen_alto(v):
        s += 3
    if (c[-1] - c[-2]) > (0.0004 * precio):
        s += 2
    if (c[-1] - c[-5]) > (0.0005 * precio):
        s += 1

    return s

def stats_msg():
    winrate = (ganadoras / operaciones * 100) if operaciones > 0 else 0
    return f"""
📊 <b>STATS</b>
💰 PnL: {ganancia_total:.2f}
📈 Trades: {operaciones}
🏆 Winrate: {winrate:.1f}%
📉 Racha pérdidas: {racha_perdidas}
"""

# ================= LOOP =================

while True:
    try:

        # ===== CONTROL DRAWDOWN =====
        if ganancia_total <= drawdown_max:
            enviar_alerta("🛑 STOP GLOBAL POR DRAWDOWN")
            time.sleep(300)
            continue

        # ===== GESTIÓN =====
        if estado:
            c, a, b, v = get_klines(symbol_activo, "1m", 20)
            precio = c[-1]

            ganancia = precio - entrada
            if precio > max_precio:
                max_precio = precio

            atr_val = atr(a, b, c)

            sl = max(
                min(c[-5:]),
                entrada - (1.5 * atr_val),
                entrada - (0.0015 * entrada)  # SL CAP
            )

            riesgo = entrada - sl
            tp = entrada + riesgo * 2

            trailing = (max_precio - entrada) * 0.4

            if precio <= sl:
                estado = False
                operaciones += 1
                ganancia_total += ganancia
                racha_perdidas += 1

                enviar_alerta(f"🛑 SL {symbol_activo}\n{ganancia:.4f}\n{stats_msg()}")

                cooldown_symbol[symbol_activo] = time.time()

            elif precio >= tp:
                estado = False
                operaciones += 1
                ganadoras += 1
                ganancia_total += ganancia
                racha_perdidas = 0

                enviar_alerta(f"💰 TP {symbol_activo}\n+{ganancia:.4f}\n{stats_msg()}")

                cooldown_symbol[symbol_activo] = time.time()

            elif max_precio - precio >= trailing and ganancia > 0:
                estado = False
                operaciones += 1
                ganadoras += 1
                ganancia_total += ganancia
                racha_perdidas = 0

                enviar_alerta(f"💰 TRAILING {symbol_activo}\n+{ganancia:.4f}\n{stats_msg()}")

                cooldown_symbol[symbol_activo] = time.time()

            time.sleep(5)
            continue

        # ===== PAUSA POR RACHAS =====
        if racha_perdidas >= 3:
            enviar_alerta("⛔ PAUSA POR MAL RENDIMIENTO")
            time.sleep(120)
            racha_perdidas = 0
            continue

        mejor = None
        mejor_score = 0

        for symbol in symbols:

            if symbol in cooldown_symbol:
                if time.time() - cooldown_symbol[symbol] < 30:
                    continue

            c, a, b, v = get_klines(symbol, "1m", 50)
            precio = c[-1]

            # ===== FILTROS =====

            # anti FOMO
            if (c[-1] - c[-2]) / c[-2] > 0.002:
                continue

            # volatilidad BTC extra
            if symbol == "BTCUSDT":
                if (c[-1] - c[-3]) / c[-3] > 0.003:
                    continue

            s = score(c, a, b, v, precio)

            if s > mejor_score:
                mejor_score = s
                mejor = (symbol, precio, c, a, b)

        if mejor and mejor_score >= 9:
            symbol_activo, entrada, c, a, b = mejor
            max_precio = entrada
            estado = True

            enviar_alerta(
                f"🚀 ENTRY {symbol_activo}\n{entrada:.4f}\nScore {mejor_score}\n{stats_msg()}"
            )

        time.sleep(5)

    except Exception as e:
        print("Error:", e)
        time.sleep(5)
