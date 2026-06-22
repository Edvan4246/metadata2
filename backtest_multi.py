#!/usr/bin/env python3
"""Backtest multi-símbolo com múltiplas estratégias (Sniper Pro V7, Fibonacci, Bill Williams).

Uso:
    python3 backtest_multi.py --data-dir ./historico --estrategia sniper
    python3 backtest_multi.py --data-dir ./historico --estrategia fibonacci
    python3 backtest_multi.py --data-dir ./historico --estrategia williams

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

    df["sl_compra"] = df["close"] - df["atr"]
    df["tp_compra"] = df["close"] + df["atr"] * 2
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

    df["sl_compra"] = swing_low
    df["tp_compra"] = swing_high + amplitude * 0.618
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

    df["sl_compra"] = ultimo_fractal_baixa
    df["tp_compra"] = df["close"] + (df["close"] - ultimo_fractal_baixa) * 2
    df["sl_venda"] = ultimo_fractal_alta
    df["tp_venda"] = df["close"] - (ultimo_fractal_alta - df["close"]) * 2
    return df


ESTRATEGIAS = {
    "sniper": aplicar_estrategia_sniper,
    "fibonacci": aplicar_estrategia_fibonacci,
    "williams": aplicar_estrategia_williams,
}


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

        entrada = row["close"]
        if compra_forte:
            sl, tp = row["sl_compra"], row["tp_compra"]
        else:
            sl, tp = row["sl_venda"], row["tp_venda"]

        if pd.isna(sl) or pd.isna(tp):
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


def carregar_csv(caminho):
    df = pd.read_csv(caminho)
    df.columns = [c.strip().lower() for c in df.columns]
    faltando = {"time", "open", "high", "low", "close"} - set(df.columns)
    if faltando:
        raise ValueError(f"colunas faltando: {faltando}")
    return df


def main():
    parser = argparse.ArgumentParser(description="Backtest multi-símbolo com múltiplas estratégias")
    parser.add_argument("--data-dir", required=True, help="pasta com um CSV por símbolo")
    parser.add_argument("--estrategia", choices=sorted(ESTRATEGIAS), default="sniper",
                         help="lógica de entrada/saída a testar")
    parser.add_argument("--ema-rapida", type=int, default=9)
    parser.add_argument("--ema-lenta", type=int, default=21)
    parser.add_argument("--rsi-periodo", type=int, default=14)
    parser.add_argument("--atr-periodo", type=int, default=14)
    parser.add_argument("--fib-lookback", type=int, default=20,
                         help="[fibonacci] nº de barras usado para achar o swing high/low")
    parser.add_argument("--risco-pct", type=float, default=1.0)
    parser.add_argument("--custo-pct-risco", type=float, default=5.0,
                         help="custo (comissão) por trade, como %% do valor arriscado na operação")
    parser.add_argument("--slippage-pct-risco", type=float, default=2.0,
                         help="slippage na saída, como %% da distância entrada-stop da operação")
    parser.add_argument("--capital-inicial", type=float, default=1000.0)
    args = parser.parse_args()

    arquivos = sorted(glob.glob(os.path.join(args.data_dir, "*.csv")))
    if not arquivos:
        print(f"Nenhum CSV encontrado em {args.data_dir}")
        return

    aplicar_estrategia = ESTRATEGIAS[args.estrategia]

    resultados = []
    for caminho in arquivos:
        simbolo = os.path.splitext(os.path.basename(caminho))[0]
        try:
            df = carregar_csv(caminho)
            df = calcular_indicadores(df, args.ema_rapida, args.ema_lenta, args.rsi_periodo, args.atr_periodo)
            if args.estrategia == "fibonacci":
                df = aplicar_estrategia(df, args.fib_lookback)
            else:
                df = aplicar_estrategia(df)
            resultado = backtest_simbolo(df, args.risco_pct, args.custo_pct_risco, args.slippage_pct_risco, args.capital_inicial)
            resultado["simbolo"] = simbolo
            resultados.append(resultado)
        except Exception as e:
            print(f"Erro ao processar {simbolo}: {e}")

    if not resultados:
        print("Nenhum resultado gerado.")
        return

    print(f"Estratégia: {args.estrategia}\n")

    colunas = ["simbolo", "trades", "win_rate_pct", "retorno_pct", "max_drawdown_pct", "fator_lucro"]
    largura = {c: max(len(c), max(len(str(r[c])) for r in resultados)) for c in colunas}

    cabecalho = " | ".join(c.ljust(largura[c]) for c in colunas)
    print(cabecalho)
    print("-" * len(cabecalho))
    for r in sorted(resultados, key=lambda x: x["retorno_pct"], reverse=True):
        print(" | ".join(str(r[c]).ljust(largura[c]) for c in colunas))


if __name__ == "__main__":
    main()
