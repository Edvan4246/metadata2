#!/usr/bin/env python3
"""Backtest multi-símbolo com múltiplas estratégias (Sniper Pro V7, Fibonacci,
Bill Williams, Zonas de Suporte/Resistência, Candle Range Theory).

Uso:
    python3 backtest_multi.py --data-dir ./historico --estrategia sniper
    python3 backtest_multi.py --data-dir ./historico --estrategia fibonacci
    python3 backtest_multi.py --data-dir ./historico --estrategia williams
    python3 backtest_multi.py --data-dir ./historico --estrategia sr_zonas
    python3 backtest_multi.py --data-dir ./historico --estrategia crt
    python3 backtest_multi.py --data-dir ./historico --estrategia auto

Lê um CSV por símbolo (colunas: time,open,high,low,close,volume) e imprime
uma tabela comparativa de desempenho por símbolo, ordenada por retorno.

Os CSVs podem ser gerados pelo script mt5_export_historico.mq5, executado
no MetaTrader 5 (Arquivo > Abrir Pasta de Dados > MQL5/Files).
"""
import argparse
import glob
import os

import numpy as np
import pandas as pd


def calcular_indicadores(df, ema_rapida, ema_lenta, rsi_periodo, atr_periodo):
    df["ema_fast"] = df["close"].ewm(span=ema_rapida, adjust=False).mean()
    df["ema_slow"] = df["close"].ewm(span=ema_lenta, adjust=False).mean()

    delta = df["close"].diff()
    ganho = delta.clip(lower=0)
    perda = -delta.clip(upper=0)
    media_ganho = ganho.ewm(alpha=1 / rsi_periodo, adjust=False).mean()
    media_perda = perda.ewm(alpha=1 / rsi_periodo, adjust=False).mean()
    rs = media_ganho / media_perda.replace(0, np.nan)
    df["rsi"] = (100 - (100 / (1 + rs))).fillna(50)

    tr1 = df["high"] - df["low"]
    tr2 = (df["high"] - df["close"].shift()).abs()
    tr3 = (df["low"] - df["close"].shift()).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    df["atr"] = tr.ewm(alpha=1 / atr_periodo, adjust=False).mean()

    return df


def aplicar_estrategia_sniper(df):
    """Tendência (EMA9/21) + candle de rompimento + filtro RSI. SL/TP em múltiplos de ATR."""
    anterior_high = df["high"].shift(1)
    anterior_low = df["low"].shift(1)

    candle_compra = (df["close"] > df["open"]) & (df["close"] > anterior_high)
    candle_venda = (df["close"] < df["open"]) & (df["close"] < anterior_low)

    tendencia_alta = df["ema_fast"] > df["ema_slow"]
    tendencia_baixa = df["ema_fast"] < df["ema_slow"]

    rsi_compra = df["rsi"] > 50
    rsi_venda = df["rsi"] < 50

    sinal_compra = tendencia_alta & candle_compra & rsi_compra
    sinal_venda = tendencia_baixa & candle_venda & rsi_venda

    df["compra_forte"] = (sinal_compra & (df["close"] > df["ema_fast"])).fillna(False)
    df["venda_forte"] = (sinal_venda & (df["close"] < df["ema_fast"])).fillna(False)

    df["entrada_compra"] = df["close"]
    df["sl_compra"] = df["close"] - df["atr"]
    df["tp_compra"] = df["close"] + df["atr"] * 2
    df["entrada_venda"] = df["close"]
    df["sl_venda"] = df["close"] + df["atr"]
    df["tp_venda"] = df["close"] - df["atr"] * 2
    return df


def aplicar_estrategia_fibonacci(df, lookback):
    """Pullback até a zona de retração 50-78,6% de um swing recente, a favor da
    tendência (EMA9/21), com alvo na extensão 61,8% além do swing e stop no
    extremo do swing oposto."""
    swing_high = df["high"].rolling(lookback).max().shift(1)
    swing_low = df["low"].rolling(lookback).min().shift(1)
    amplitude = swing_high - swing_low
    amplitude_valida = amplitude > 0

    tendencia_alta = df["ema_fast"] > df["ema_slow"]
    tendencia_baixa = df["ema_fast"] < df["ema_slow"]

    fib_50_alta = swing_high - amplitude * 0.5
    fib_786_alta = swing_high - amplitude * 0.786
    pullback_compra = (
        (df["low"] <= fib_50_alta)
        & (df["low"] >= fib_786_alta)
        & (df["close"] > df["open"])
        & (df["close"] > fib_50_alta)
    )

    fib_50_baixa = swing_low + amplitude * 0.5
    fib_786_baixa = swing_low + amplitude * 0.786
    pullback_venda = (
        (df["high"] >= fib_50_baixa)
        & (df["high"] <= fib_786_baixa)
        & (df["close"] < df["open"])
        & (df["close"] < fib_50_baixa)
    )

    df["compra_forte"] = (tendencia_alta & pullback_compra & amplitude_valida).fillna(False)
    df["venda_forte"] = (tendencia_baixa & pullback_venda & amplitude_valida).fillna(False)

    df["entrada_compra"] = df["close"]
    df["sl_compra"] = swing_low
    df["tp_compra"] = swing_high + amplitude * 0.618
    df["entrada_venda"] = df["close"]
    df["sl_venda"] = swing_high
    df["tp_venda"] = swing_low - amplitude * 0.618
    return df


def aplicar_estrategia_williams(df):
    """Sistema de Bill Williams: Alligator (jaw/teeth/lips deslocados) define a
    direção da "boca aberta", o rompimento de um Fractal confirma a entrada e o
    Awesome Oscillator filtra o momentum. Stop no fractal oposto mais recente,
    alvo em 2x essa distância (sem trailing stop nesta versão simplificada)."""
    preco_medio = (df["high"] + df["low"]) / 2

    jaw = preco_medio.ewm(alpha=1 / 13, adjust=False).mean().shift(8)
    teeth = preco_medio.ewm(alpha=1 / 8, adjust=False).mean().shift(5)
    lips = preco_medio.ewm(alpha=1 / 5, adjust=False).mean().shift(3)

    ao = preco_medio.rolling(5).mean() - preco_medio.rolling(34).mean()

    fractal_alta = (
        (df["high"].shift(2) > df["high"].shift(4))
        & (df["high"].shift(2) > df["high"].shift(3))
        & (df["high"].shift(2) > df["high"].shift(1))
        & (df["high"].shift(2) > df["high"])
    )
    fractal_baixa = (
        (df["low"].shift(2) < df["low"].shift(4))
        & (df["low"].shift(2) < df["low"].shift(3))
        & (df["low"].shift(2) < df["low"].shift(1))
        & (df["low"].shift(2) < df["low"])
    )

    ultimo_fractal_alta = df["high"].shift(2).where(fractal_alta).ffill()
    ultimo_fractal_baixa = df["low"].shift(2).where(fractal_baixa).ffill()

    boca_alta = (lips > teeth) & (teeth > jaw)
    boca_baixa = (lips < teeth) & (teeth < jaw)

    rompeu_alta = (df["close"] > ultimo_fractal_alta) & (df["close"].shift(1) <= ultimo_fractal_alta.shift(1))
    rompeu_baixa = (df["close"] < ultimo_fractal_baixa) & (df["close"].shift(1) >= ultimo_fractal_baixa.shift(1))

    df["compra_forte"] = (rompeu_alta & boca_alta & (ao > 0)).fillna(False)
    df["venda_forte"] = (rompeu_baixa & boca_baixa & (ao < 0)).fillna(False)

    df["entrada_compra"] = df["close"]
    df["sl_compra"] = ultimo_fractal_baixa
    df["tp_compra"] = df["close"] + (df["close"] - ultimo_fractal_baixa) * 2
    df["entrada_venda"] = df["close"]
    df["sl_venda"] = ultimo_fractal_alta
    df["tp_venda"] = df["close"] - (ultimo_fractal_alta - df["close"]) * 2
    return df


def aplicar_estrategia_sr_zonas(df, margem_atr=0.15, merge_tol_atr=0.5, buffer_trigger_atr=0.1, validade_pendente=5, max_idade_zona=500, rr_minimo=1.5):
    """Suporte/Resistência como regiões (não pontos): pivôs (fractais de 5 barras)
    são agrupados em zonas; toda resistência rompida (fechamento acima do topo da
    zona) se torna suporte, e todo suporte rompido se torna resistência. Na
    tendência (EMA9/21), quando o preço testa uma zona a favor da tendência, é
    armada uma ordem pendente (buy stop / sell stop) um pouco acima/abaixo do
    teste — se o preço romper esse gatilho nas próximas barras a operação é
    executada; senão a ordem é cancelada se a zona for invalidada ou expirar.
    O alvo é a zona oposta mais próxima, mas só se ela garantir pelo menos
    rr_minimo de risco:retorno; caso contrário usa esse mínimo direto, pra não
    aceitar trades com alvo mais perto do que o stop.
    Pensada para scalping em M5 dentro de canais de tendência."""
    n = len(df)
    high = df["high"].values
    low = df["low"].values
    close = df["close"].values
    atr = df["atr"].values
    ema_fast = df["ema_fast"].values
    ema_slow = df["ema_slow"].values

    fractal_alta = (
        (df["high"].shift(2) > df["high"].shift(4))
        & (df["high"].shift(2) > df["high"].shift(3))
        & (df["high"].shift(2) > df["high"].shift(1))
        & (df["high"].shift(2) > df["high"])
    ).fillna(False).values
    fractal_baixa = (
        (df["low"].shift(2) < df["low"].shift(4))
        & (df["low"].shift(2) < df["low"].shift(3))
        & (df["low"].shift(2) < df["low"].shift(1))
        & (df["low"].shift(2) < df["low"])
    ).fillna(False).values
    valor_fractal_alta = df["high"].shift(2).values
    valor_fractal_baixa = df["low"].shift(2).values

    compra_forte = np.zeros(n, dtype=bool)
    venda_forte = np.zeros(n, dtype=bool)
    entrada_compra = np.full(n, np.nan)
    sl_compra = np.full(n, np.nan)
    tp_compra = np.full(n, np.nan)
    entrada_venda = np.full(n, np.nan)
    sl_venda = np.full(n, np.nan)
    tp_venda = np.full(n, np.nan)

    zonas = []  # cada zona: {tipo: "suporte"/"resistencia", fundo, topo, ultimo_toque}
    pendente = None  # ordem pendente tipo buy stop / sell stop

    def registrar_pivot(tipo, preco, atr_local, idx):
        if np.isnan(atr_local) or atr_local <= 0:
            return
        margem = atr_local * margem_atr
        tol = atr_local * merge_tol_atr
        for zona in zonas:
            if zona["tipo"] == tipo and zona["fundo"] - tol <= preco <= zona["topo"] + tol:
                zona["fundo"] = min(zona["fundo"], preco - margem)
                zona["topo"] = max(zona["topo"], preco + margem)
                zona["ultimo_toque"] = idx
                return
        zonas.append({"tipo": tipo, "fundo": preco - margem, "topo": preco + margem, "ultimo_toque": idx})

    for i in range(4, n):
        if fractal_alta[i]:
            registrar_pivot("resistencia", valor_fractal_alta[i], atr[i - 2], i - 2)
        if fractal_baixa[i]:
            registrar_pivot("suporte", valor_fractal_baixa[i], atr[i - 2], i - 2)

        zonas[:] = [z for z in zonas if i - z["ultimo_toque"] <= max_idade_zona]

        for zona in zonas:
            if zona["tipo"] == "resistencia" and close[i] > zona["topo"]:
                zona["tipo"] = "suporte"
                zona["ultimo_toque"] = i
            elif zona["tipo"] == "suporte" and close[i] < zona["fundo"]:
                zona["tipo"] = "resistencia"
                zona["ultimo_toque"] = i

        if pendente is not None:
            if i - pendente["criado_em"] > validade_pendente:
                pendente = None
            elif pendente["tipo"] == "compra":
                if low[i] < pendente["zona_fundo"]:
                    pendente = None
                elif high[i] >= pendente["trigger"]:
                    compra_forte[i] = True
                    entrada_compra[i] = pendente["trigger"]
                    sl_compra[i] = pendente["sl"]
                    tp_compra[i] = pendente["tp"]
                    pendente = None
            else:
                if high[i] > pendente["zona_topo"]:
                    pendente = None
                elif low[i] <= pendente["trigger"]:
                    venda_forte[i] = True
                    entrada_venda[i] = pendente["trigger"]
                    sl_venda[i] = pendente["sl"]
                    tp_venda[i] = pendente["tp"]
                    pendente = None

        if pendente is None and not compra_forte[i] and not venda_forte[i]:
            atr_i = atr[i]
            if not np.isnan(atr_i) and atr_i > 0:
                if ema_fast[i] > ema_slow[i]:
                    for zona in zonas:
                        if zona["tipo"] == "suporte" and low[i] <= zona["topo"] and high[i] >= zona["fundo"]:
                            gatilho = max(zona["topo"], high[i]) + atr_i * buffer_trigger_atr
                            sl_dist = gatilho - zona["fundo"]
                            alvo_minimo = gatilho + sl_dist * rr_minimo
                            candidatos = [z["fundo"] for z in zonas if z["tipo"] == "resistencia" and z["fundo"] > gatilho]
                            alvo_zona = min(candidatos) if candidatos else None
                            # Ignora a zona oposta como alvo se ela estiver mais perto
                            # do que o mínimo de risco:retorno exigido (alvo perto
                            # demais do gatilho é o que estava deixando o fator de
                            # lucro abaixo de 1 mesmo com boa taxa de acerto).
                            alvo = alvo_zona if (alvo_zona is not None and alvo_zona >= alvo_minimo) else alvo_minimo
                            pendente = {
                                "tipo": "compra", "trigger": gatilho, "sl": zona["fundo"], "tp": alvo,
                                "zona_fundo": zona["fundo"], "criado_em": i,
                            }
                            break
                elif ema_fast[i] < ema_slow[i]:
                    for zona in zonas:
                        if zona["tipo"] == "resistencia" and high[i] >= zona["fundo"] and low[i] <= zona["topo"]:
                            gatilho = min(zona["fundo"], low[i]) - atr_i * buffer_trigger_atr
                            sl_dist = zona["topo"] - gatilho
                            alvo_minimo = gatilho - sl_dist * rr_minimo
                            candidatos = [z["topo"] for z in zonas if z["tipo"] == "suporte" and z["topo"] < gatilho]
                            alvo_zona = max(candidatos) if candidatos else None
                            alvo = alvo_zona if (alvo_zona is not None and alvo_zona <= alvo_minimo) else alvo_minimo
                            pendente = {
                                "tipo": "venda", "trigger": gatilho, "sl": zona["topo"], "tp": alvo,
                                "zona_topo": zona["topo"], "criado_em": i,
                            }
                            break

    df["compra_forte"] = compra_forte
    df["venda_forte"] = venda_forte
    df["entrada_compra"] = entrada_compra
    df["sl_compra"] = sl_compra
    df["tp_compra"] = tp_compra
    df["entrada_venda"] = entrada_venda
    df["sl_venda"] = sl_venda
    df["tp_venda"] = tp_venda
    return df


def aplicar_estrategia_crt(df, buffer_atr=0.1, validade_pendente=3, rr_minimo=1.3):
    """Candle Range Theory (CRT/ICT): a vela anterior define um range (topo =
    high, fundo = low). Quando a vela atual varre (sweep) além desse range com
    o pavio mas fecha de volta pra dentro dele (rejeição/manipulação), é
    armada uma ordem pendente (buy stop / sell stop) no rompimento da própria
    vela de rejeição, na direção contrária à varredura. Stop além do pavio que
    varreu o range; alvo na ponta oposta do range, respeitando um risco:
    retorno mínimo (senão usa esse mínimo em vez do range, que pode ser
    estreito demais)."""
    high = df["high"].values
    low = df["low"].values
    close = df["close"].values
    open_ = df["open"].values
    atr = df["atr"].values
    n = len(df)

    compra_forte = np.zeros(n, dtype=bool)
    venda_forte = np.zeros(n, dtype=bool)
    entrada_compra = np.full(n, np.nan)
    sl_compra = np.full(n, np.nan)
    tp_compra = np.full(n, np.nan)
    entrada_venda = np.full(n, np.nan)
    sl_venda = np.full(n, np.nan)
    tp_venda = np.full(n, np.nan)

    pendente = None

    for i in range(1, n):
        ref_topo = high[i - 1]
        ref_fundo = low[i - 1]

        if pendente is not None:
            if i - pendente["criado_em"] > validade_pendente:
                pendente = None
            elif pendente["tipo"] == "compra":
                if low[i] < pendente["invalida"]:
                    pendente = None
                elif high[i] >= pendente["trigger"]:
                    compra_forte[i] = True
                    entrada_compra[i] = pendente["trigger"]
                    sl_compra[i] = pendente["sl"]
                    tp_compra[i] = pendente["tp"]
                    pendente = None
            else:
                if high[i] > pendente["invalida"]:
                    pendente = None
                elif low[i] <= pendente["trigger"]:
                    venda_forte[i] = True
                    entrada_venda[i] = pendente["trigger"]
                    sl_venda[i] = pendente["sl"]
                    tp_venda[i] = pendente["tp"]
                    pendente = None

        if pendente is None and not compra_forte[i] and not venda_forte[i]:
            atr_i = atr[i]
            if not np.isnan(atr_i) and atr_i > 0 and not np.isnan(ref_topo) and not np.isnan(ref_fundo):
                varreu_fundo = low[i] < ref_fundo
                rejeitou_para_cima = close[i] > ref_fundo and close[i] > open_[i]
                if varreu_fundo and rejeitou_para_cima:
                    gatilho = high[i] + atr_i * buffer_atr
                    sl = low[i] - atr_i * buffer_atr
                    sl_dist = gatilho - sl
                    alvo_minimo = gatilho + sl_dist * rr_minimo
                    tp = ref_topo if ref_topo >= alvo_minimo else alvo_minimo
                    pendente = {"tipo": "compra", "trigger": gatilho, "sl": sl, "tp": tp, "invalida": sl, "criado_em": i}

                varreu_topo = high[i] > ref_topo
                rejeitou_para_baixo = close[i] < ref_topo and close[i] < open_[i]
                if pendente is None and varreu_topo and rejeitou_para_baixo:
                    gatilho = low[i] - atr_i * buffer_atr
                    sl = high[i] + atr_i * buffer_atr
                    sl_dist = sl - gatilho
                    alvo_minimo = gatilho - sl_dist * rr_minimo
                    tp = ref_fundo if ref_fundo <= alvo_minimo else alvo_minimo
                    pendente = {"tipo": "venda", "trigger": gatilho, "sl": sl, "tp": tp, "invalida": sl, "criado_em": i}

    df["compra_forte"] = compra_forte
    df["venda_forte"] = venda_forte
    df["entrada_compra"] = entrada_compra
    df["sl_compra"] = sl_compra
    df["tp_compra"] = tp_compra
    df["entrada_venda"] = entrada_venda
    df["sl_venda"] = sl_venda
    df["tp_venda"] = tp_venda
    return df


ESTRATEGIAS = {
    "sniper": aplicar_estrategia_sniper,
    "fibonacci": aplicar_estrategia_fibonacci,
    "williams": aplicar_estrategia_williams,
    "sr_zonas": aplicar_estrategia_sr_zonas,
    "crt": aplicar_estrategia_crt,
}

# Mapa símbolo -> estratégia (sr_zonas ou crt), separado por timeframe porque
# --validar-auto (janela de 180 dias fora da amostra de 6 meses) deu
# resultados bem diferentes pros dois:
#
# M5: o histórico exportado é curto (a janela de 180 dias cobre o mesmo
# período usado pra montar este mapa, não é validação independente de
# verdade). Mantido o roteamento por símbolo por ser a melhor informação
# disponível, mas sem confirmação real ainda.
#
# H1: o histórico é longo o bastante pra a janela de 180 dias ser de fato
# um período diferente, e nesse teste real o roteamento por símbolo bateu
# só 4/8 (e os vencedores reais da janela também ficaram 4-4 entre as
# estratégias) — ou seja, escolher por símbolo no H1 não é melhor que
# escolher ao acaso. Por isso H1 usa uma única estratégia fixa pra todos os
# símbolos: sr_zonas, que teve o maior retorno agregado e o menor
# drawdown/pior caso no histórico completo (uma vantagem marginal, não uma
# confirmação forte).
MAPA_AUTO = {
    "XAUUSD.c_PERIOD_M5": "sr_zonas",
    "GBPJPY.c_PERIOD_M5": "sr_zonas",
    "GBPUSD_PERIOD_M5": "sr_zonas",
    "EURUSD_PERIOD_M5": "sr_zonas",
    "USDCAD_PERIOD_M5": "crt",
    "XAGUSD.c_PERIOD_M5": "crt",
    "USDJPY_PERIOD_M5": "crt",
    "AUDUSD_PERIOD_M5": "crt",
    "XAUUSD.c_PERIOD_H1": "sr_zonas",
    "USDCAD_PERIOD_H1": "sr_zonas",
    "XAGUSD.c_PERIOD_H1": "sr_zonas",
    "AUDUSD_PERIOD_H1": "sr_zonas",
    "GBPUSD_PERIOD_H1": "sr_zonas",
    "EURUSD_PERIOD_H1": "sr_zonas",
    "USDJPY_PERIOD_H1": "sr_zonas",
    "GBPJPY.c_PERIOD_H1": "sr_zonas",
}
ESTRATEGIA_AUTO_PADRAO = "sr_zonas"


def aplicar_estrategia_por_nome(df, nome, args):
    aplicar = ESTRATEGIAS[nome]
    if nome == "fibonacci":
        return aplicar(df, args.fib_lookback)
    if nome == "sr_zonas":
        return aplicar(
            df,
            margem_atr=args.sr_margem_atr,
            merge_tol_atr=args.sr_merge_tol_atr,
            buffer_trigger_atr=args.sr_buffer_atr,
            validade_pendente=args.sr_validade_pendente,
            rr_minimo=args.sr_rr_minimo,
        )
    if nome == "crt":
        return aplicar(
            df,
            buffer_atr=args.crt_buffer_atr,
            validade_pendente=args.crt_validade_pendente,
            rr_minimo=args.crt_rr_minimo,
        )
    return aplicar(df)


def backtest_simbolo(df, risco_pct, custo_pct_risco, slippage_pct_risco, capital_inicial):
    df = df.reset_index(drop=True)
    equity = capital_inicial
    pico_equity = capital_inicial
    max_drawdown = 0.0
    posicao = None
    trades = []

    for i in range(2, len(df)):
        row = df.iloc[i]

        if posicao is not None:
            saiu = False
            preco_saida = None
            if posicao["tipo"] == "compra":
                if row["low"] <= posicao["sl"]:
                    preco_saida, saiu = posicao["sl"], True
                elif row["high"] >= posicao["tp"]:
                    preco_saida, saiu = posicao["tp"], True
            else:
                if row["high"] >= posicao["sl"]:
                    preco_saida, saiu = posicao["sl"], True
                elif row["low"] <= posicao["tp"]:
                    preco_saida, saiu = posicao["tp"], True

            if saiu:
                # Slippage e comissão são proporcionais ao risco da operação
                # (distância entrada-stop, não ao valor nocional), para que o
                # custo seja comparável entre ativos com escalas de preço
                # muito diferentes.
                deslizamento = posicao["risco_distancia"] * (slippage_pct_risco / 100)
                if posicao["tipo"] == "compra":
                    preco_saida_ajustado = preco_saida - deslizamento
                    resultado = (preco_saida_ajustado - posicao["entrada"]) * posicao["qty"]
                else:
                    preco_saida_ajustado = preco_saida + deslizamento
                    resultado = (posicao["entrada"] - preco_saida_ajustado) * posicao["qty"]

                custo_comissao = posicao["risco_valor"] * (custo_pct_risco / 100)
                resultado -= custo_comissao

                equity += resultado
                trades.append(resultado)
                posicao = None

        pico_equity = max(pico_equity, equity)
        if pico_equity > 0:
            max_drawdown = max(max_drawdown, (pico_equity - equity) / pico_equity)

        if posicao is not None:
            continue

        compra_forte = bool(row["compra_forte"])
        venda_forte = bool(row["venda_forte"])
        if not (compra_forte or venda_forte):
            continue

        if compra_forte:
            entrada, sl, tp = row["entrada_compra"], row["sl_compra"], row["tp_compra"]
        else:
            entrada, sl, tp = row["entrada_venda"], row["sl_venda"], row["tp_venda"]

        if pd.isna(entrada) or pd.isna(sl) or pd.isna(tp):
            continue

        risco_distancia = abs(entrada - sl)
        if risco_distancia <= 0:
            continue

        risco_valor = equity * (risco_pct / 100)
        qty = risco_valor / risco_distancia

        posicao = {
            "tipo": "compra" if compra_forte else "venda",
            "entrada": entrada,
            "sl": sl,
            "tp": tp,
            "qty": qty,
            "risco_distancia": risco_distancia,
            "risco_valor": risco_valor,
        }

    total_trades = len(trades)
    vencedores = sum(1 for t in trades if t > 0)
    win_rate = (vencedores / total_trades * 100) if total_trades else 0.0
    retorno_pct = (equity - capital_inicial) / capital_inicial * 100

    ganhos = sum(t for t in trades if t > 0)
    perdas = sum(t for t in trades if t <= 0)
    if perdas != 0:
        fator_lucro = round(ganhos / abs(perdas), 2)
    elif ganhos > 0:
        fator_lucro = "inf"
    else:
        fator_lucro = 0.0

    return {
        "trades": total_trades,
        "win_rate_pct": round(win_rate, 2),
        "retorno_pct": round(retorno_pct, 2),
        "max_drawdown_pct": round(max_drawdown * 100, 2),
        "fator_lucro": fator_lucro,
    }


def _fator_lucro_ordenavel(fator_lucro):
    return float("inf") if isinstance(fator_lucro, str) else fator_lucro


def validar_mapa_auto(arquivos, args):
    """Roda sr_zonas e crt, separadamente, só na janela mais recente
    (args.dias_teste, fora da amostra usada pra montar o MAPA_AUTO) e
    compara qual teria vencido nesse período contra o que está fixado no
    mapa. Serve pra checar se a escolha por símbolo é robusta ou só
    ajuste ao período usado para decidir."""
    linhas = []
    for caminho in arquivos:
        simbolo = os.path.splitext(os.path.basename(caminho))[0]
        try:
            df_completo = carregar_csv(caminho)
            df_completo = calcular_indicadores(df_completo, args.ema_rapida, args.ema_lenta, args.rsi_periodo, args.atr_periodo)
            df_teste = filtrar_ultimos_dias(df_completo, args.dias_teste)
            if df_teste.empty:
                continue

            resultados_periodo = {}
            for nome in ("sr_zonas", "crt"):
                df_aplicado = aplicar_estrategia_por_nome(df_teste.copy(), nome, args)
                resultados_periodo[nome] = backtest_simbolo(
                    df_aplicado, args.risco_pct, args.custo_pct_risco, args.slippage_pct_risco, args.capital_inicial
                )

            fl_sr = resultados_periodo["sr_zonas"]["fator_lucro"]
            fl_crt = resultados_periodo["crt"]["fator_lucro"]
            sr_val = _fator_lucro_ordenavel(fl_sr)
            crt_val = _fator_lucro_ordenavel(fl_crt)
            if sr_val > crt_val:
                vencedor_periodo = "sr_zonas"
            elif crt_val > sr_val:
                vencedor_periodo = "crt"
            else:
                vencedor_periodo = "empate"

            estrategia_mapa = MAPA_AUTO.get(simbolo, ESTRATEGIA_AUTO_PADRAO)
            if vencedor_periodo == "empate":
                bateu = "empate"
            else:
                bateu = "sim" if vencedor_periodo == estrategia_mapa else "nao"

            linhas.append({
                "simbolo": simbolo,
                "trades_sr": resultados_periodo["sr_zonas"]["trades"],
                "fl_sr": fl_sr,
                "trades_crt": resultados_periodo["crt"]["trades"],
                "fl_crt": fl_crt,
                "estrategia_mapa": estrategia_mapa,
                "vencedor_periodo": vencedor_periodo,
                "bateu_mapa": bateu,
            })
        except Exception as e:
            print(f"Erro ao validar {simbolo}: {e}")
    return linhas


def carregar_csv(caminho):
    df = pd.read_csv(caminho)
    df.columns = [c.strip().lower() for c in df.columns]
    faltando = {"time", "open", "high", "low", "close"} - set(df.columns)
    if faltando:
        raise ValueError(f"colunas faltando: {faltando}")
    df["time"] = pd.to_datetime(df["time"], errors="coerce")
    return df


def filtrar_ultimos_dias(df, dias):
    fim = df["time"].max()
    if pd.isna(fim):
        return df
    inicio = fim - pd.Timedelta(days=dias)
    return df[df["time"] > inicio].reset_index(drop=True)


def main():
    parser = argparse.ArgumentParser(description="Backtest multi-símbolo com múltiplas estratégias")
    parser.add_argument("--data-dir", required=True, help="pasta com um CSV por símbolo")
    parser.add_argument("--estrategia", choices=sorted(list(ESTRATEGIAS) + ["auto"]), default="sniper",
                         help="lógica de entrada/saída a testar. 'auto' escolhe por símbolo entre "
                              "sr_zonas/crt conforme o MAPA_AUTO (melhor fator de lucro observado)")
    parser.add_argument("--ema-rapida", type=int, default=9)
    parser.add_argument("--ema-lenta", type=int, default=21)
    parser.add_argument("--rsi-periodo", type=int, default=14)
    parser.add_argument("--atr-periodo", type=int, default=14)
    parser.add_argument("--fib-lookback", type=int, default=20,
                         help="[fibonacci] nº de barras usado para achar o swing high/low")
    parser.add_argument("--sr-margem-atr", type=float, default=0.15,
                         help="[sr_zonas] meia-largura da zona de suporte/resistência, em múltiplos do ATR")
    parser.add_argument("--sr-merge-tol-atr", type=float, default=0.5,
                         help="[sr_zonas] distância (em ATR) para agrupar pivôs na mesma zona")
    parser.add_argument("--sr-buffer-atr", type=float, default=0.1,
                         help="[sr_zonas] distância do gatilho do buy/sell stop além do teste da zona, em ATR")
    parser.add_argument("--sr-validade-pendente", type=int, default=5,
                         help="[sr_zonas] nº de barras que a ordem pendente fica armada antes de cancelar")
    parser.add_argument("--sr-rr-minimo", type=float, default=1.5,
                         help="[sr_zonas] risco:retorno mínimo aceito; ignora zonas opostas mais próximas que isso")
    parser.add_argument("--crt-buffer-atr", type=float, default=0.1,
                         help="[crt] distância do gatilho/stop além da vela de rejeição, em ATR")
    parser.add_argument("--crt-validade-pendente", type=int, default=3,
                         help="[crt] nº de barras que a ordem pendente fica armada antes de cancelar")
    parser.add_argument("--crt-rr-minimo", type=float, default=1.3,
                         help="[crt] risco:retorno mínimo aceito; ignora o range como alvo se for mais próximo que isso")
    parser.add_argument("--dias", type=float, default=None,
                         help="simula só os últimos N dias do histórico (ex.: 30 para 1 mês). "
                              "Os indicadores ainda usam todo o histórico carregado, só a simulação é recortada")
    parser.add_argument("--risco-pct", type=float, default=1.0)
    parser.add_argument("--custo-pct-risco", type=float, default=5.0,
                         help="custo (comissão) por trade, como %% do valor arriscado na operação")
    parser.add_argument("--slippage-pct-risco", type=float, default=2.0,
                         help="slippage na saída, como %% da distância entrada-stop da operação")
    parser.add_argument("--capital-inicial", type=float, default=1000.0)
    parser.add_argument("--validar-auto", action="store_true",
                         help="em vez de simular, testa se o MAPA_AUTO (sr_zonas vs crt por símbolo) "
                              "se confirma numa janela recente fora da amostra usada pra montá-lo")
    parser.add_argument("--dias-teste", type=float, default=180,
                         help="[--validar-auto] tamanho da janela recente (em dias) usada como teste fora da amostra; padrão 180 (~6 meses)")
    args = parser.parse_args()

    arquivos = sorted(glob.glob(os.path.join(args.data_dir, "*.csv")))
    if not arquivos:
        print(f"Nenhum CSV encontrado em {args.data_dir}")
        return

    if args.validar_auto:
        linhas = validar_mapa_auto(arquivos, args)
        if not linhas:
            print("Nenhum resultado gerado.")
            return
        print(f"Validação do MAPA_AUTO nos últimos {args.dias_teste:g} dias (capital inicial ${args.capital_inicial:g})\n")
        colunas = ["simbolo", "trades_sr", "fl_sr", "trades_crt", "fl_crt", "estrategia_mapa", "vencedor_periodo", "bateu_mapa"]
        largura = {c: max(len(c), max(len(str(r[c])) for r in linhas)) for c in colunas}
        cabecalho = " | ".join(c.ljust(largura[c]) for c in colunas)
        print(cabecalho)
        print("-" * len(cabecalho))
        for r in sorted(linhas, key=lambda x: x["simbolo"]):
            print(" | ".join(str(r[c]).ljust(largura[c]) for c in colunas))
        total = len(linhas)
        bateram = sum(1 for r in linhas if r["bateu_mapa"] == "sim")
        empates = sum(1 for r in linhas if r["bateu_mapa"] == "empate")
        print(f"\n{bateram}/{total} confirmaram a escolha do MAPA_AUTO ({empates} empate(s))")
        return

    resultados = []
    for caminho in arquivos:
        simbolo = os.path.splitext(os.path.basename(caminho))[0]
        try:
            df = carregar_csv(caminho)
            df = calcular_indicadores(df, args.ema_rapida, args.ema_lenta, args.rsi_periodo, args.atr_periodo)
            if args.estrategia == "auto":
                nome_estrategia = MAPA_AUTO.get(simbolo, ESTRATEGIA_AUTO_PADRAO)
            else:
                nome_estrategia = args.estrategia
            df = aplicar_estrategia_por_nome(df, nome_estrategia, args)
            if args.dias is not None:
                df = filtrar_ultimos_dias(df, args.dias)
            resultado = backtest_simbolo(df, args.risco_pct, args.custo_pct_risco, args.slippage_pct_risco, args.capital_inicial)
            resultado["simbolo"] = simbolo
            resultado["estrategia"] = nome_estrategia
            resultados.append(resultado)
        except Exception as e:
            print(f"Erro ao processar {simbolo}: {e}")

    if not resultados:
        print("Nenhum resultado gerado.")
        return

    print(f"Estratégia: {args.estrategia}\n")

    colunas = ["simbolo", "trades", "win_rate_pct", "retorno_pct", "max_drawdown_pct", "fator_lucro"]
    if args.estrategia == "auto":
        colunas.append("estrategia")
    largura = {c: max(len(c), max(len(str(r[c])) for r in resultados)) for c in colunas}

    cabecalho = " | ".join(c.ljust(largura[c]) for c in colunas)
    print(cabecalho)
    print("-" * len(cabecalho))
    for r in sorted(resultados, key=lambda x: x["retorno_pct"], reverse=True):
        print(" | ".join(str(r[c]).ljust(largura[c]) for c in colunas))


if __name__ == "__main__":
    main()
