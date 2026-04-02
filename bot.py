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

racha_perdidas = 0
ganancia_acumulada = 0
operaciones_totales = 0
operaciones_ganadoras = 0

enviar_alerta("📊 <b>BOT CUANTITATIVO v3 ACTIVO</b>\n⏰ " + datetime.now().strftime("%H:%M:%S"))

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
    rs = ag / ap
    return 100 - (100 / (1 + rs))

def macd(cierres):
    ema12 = ema(cierres, 12)
    ema26 = ema(cierres, 26)
    linea = [e12 - e26 for e12, e26 in zip(ema12, ema26)]
    senal = ema(linea, 9)
    hist = [l - s for l, s in zip(linea, senal)]
    return linea[-1], senal[-1], hist[-1], hist[-2]

def atr(altos, bajos, cierres, n=14):
    trs = []
    for i in range(1, len(cierres)):
        tr = max(
            altos[i] - bajos[i],
            abs(altos[i] - cierres[i-1]),
            abs(bajos[i] - cierres[i-1])
        )
        trs.append(tr)
    if len(trs) < n:
        return cierres[-1] * 0.002
    return sum(trs[-n:]) / n

def bollinger(cierres, n=20, dev=2):
    ventana = cierres[-n:]
    media = sum(ventana) / n
    std = math.sqrt(sum((x - media)**2 for x in ventana) / n)
    return media, media + dev * std, media - dev * std

def volumen_alto(volumenes, n=20):
    vol_actual = volumenes[-1]
    vol_prom = sum(volumenes[-n:-1]) / (n - 1)
    return vol_actual > vol_prom * 1.2

def tendencia_ema(cierres):
    return ema(cierres, 9)[-1] > ema(cierres, 21)[-1]

def slope_ema(cierres):
    e = ema(cierres, 9)
    return e[-1] > e[-3]

def detectar_pullback(cierres):
    subida = cierres[-5] < cierres[-4] < cierres[-3]
    retroceso = cierres[-3] > cierres[-2]
    confirmacion = cierres[-1] > cierres[-2] and cierres[-2] > cierres[-3]
    e9 = ema(cierres, 9)
    soporte = cierres[-1] >= e9[-1] * 0.999
    return subida and retroceso and confirmacion and soporte

# ================= SCORE =================

def score(cierres, altos, bajos, volumenes, precio):
    s = 0
    detalles = []

    if tendencia_ema(cierres):
        s += 2; detalles.append("EMA")

    if slope_ema(cierres):
        s += 1; detalles.append("Slope")

    if detectar_pullback(cierres):
        s += 2; detalles.append("PB")

    r = rsi(cierres)
    if 45 <= r <= 68:
        s += 2; detalles.append("RSI")
    elif r > 68:
        s -= 1

    linea, senal, hist, hist_prev = macd(cierres)
    if linea > senal:
        s += 1; detalles.append("MACD")
    if hist > 0 and hist > hist_prev:
        s += 1; detalles.append("Hist")

    if volumen_alto(volumenes):
        s += 3; detalles.append("VOL")

    bb_media, _, _ = bollinger(cierres)
    if cierres[-1] > bb_media:
        s += 1; detalles.append("BB")

    cambio_5 = (cierres[-1] - cierres[-5]) / cierres[-5]
    if 0.0005 < cambio_5 < 0.01:
        s += 1; detalles.append("MOM")

    return s, detalles, r

# ================= LOOP =================

while True:
    try:

        if estado:
            cierres, altos, bajos, volumenes = get_klines(symbol_activo, "1m", 20)
            precio = cierres[-1]

            ganancia = precio - entrada
            if precio > max_precio:
                max_precio = precio

            atr_val = atr(altos, bajos, cierres)

            sl = max(
                min(cierres[-5:]),
                entrada - (1.5 * atr_val),
                entrada - (0.002 * entrada)
            )

            riesgo = entrada - sl
            tp1 = entrada + riesgo * 1.5
            tp2 = entrada + riesgo * 2.0  # ajustado

            trailing = (max_precio - entrada) * 0.4

            if precio <= sl:
                enviar_alerta(f"🛑 SL {symbol_activo}\n{precio:.4f}\n{ganancia:.4f}")
                estado = False
                racha_perdidas += 1

            elif precio >= tp2:
                enviar_alerta(f"💰 TP2 {symbol_activo}\n+{ganancia:.4f}")
                estado = False
                racha_perdidas = 0

            elif max_precio - precio >= trailing and ganancia > 0:
                enviar_alerta(f"💰 TRAILING {symbol_activo}\n+{ganancia:.4f}")
                estado = False
                racha_perdidas = 0

            time.sleep(5)
            continue

        if racha_perdidas >= 2:
            time.sleep(90)
            racha_perdidas = 0
            continue

        mejor = None
        mejor_score = 0

        for symbol in symbols:
            try:
                c, a, b, v = get_klines(symbol, "1m", 50)
                precio = c[-1]

                # ===== FILTROS NUEVOS =====

                # anti explosión
                if (c[-1] - c[-2]) / c[-2] > 0.002:
                    continue

                # distancia EMA
                if (precio - ema(c, 9)[-1]) / precio > 0.0015:
                    continue

                # fuerza mínima
                if (c[-1] - c[-2]) < (0.0004 * precio):
                    continue

                s, det, r = score(c, a, b, v, precio)

                if s > mejor_score:
                    mejor_score = s
                    mejor = (symbol, precio, c, a, b)

            except:
                continue

        if mejor and mejor_score >= 9:
            symbol_activo, entrada, c, a, b = mejor
            max_precio = entrada
            estado = True

            enviar_alerta(f"🚀 ENTRY {symbol_activo}\n{entrada:.4f}\nScore {mejor_score}")

        time.sleep(5)

    except Exception as e:
        print("Error:", e)
        time.sleep(5)
