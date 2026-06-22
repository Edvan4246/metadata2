#!/usr/bin/env python3
"""Backtest multi-símbolo da estratégia Sniper Pro V7.

Uso:
    python3 backtest_multi.py --data-dir ./historico

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


def backtest_simbolo(df, risco_pct, custo_pct_risco, slippage_pct_atr, capital_inicial):
    df = df.reset_index(drop=True)
    equity = capital_inicial
    pico_equity = capital_inicial
    max_drawdown = 0.0
    posicao = None
    trades = []

    for i in range(2, len(df)):
        row = df.iloc[i]
        anterior = df.iloc[i - 1]

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
                # (não ao valor nocional), para que o custo seja comparável
                # entre ativos com escalas de preço muito diferentes.
                deslizamento = posicao["atr_entrada"] * (slippage_pct_atr / 100)
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
        if pd.isna(row["atr"]) or row["atr"] <= 0:
            continue

        tendencia_alta = row["ema_fast"] > row["ema_slow"]
        tendencia_baixa = row["ema_fast"] < row["ema_slow"]

        candle_compra = (row["close"] > row["open"]) and (row["close"] > anterior["high"])
        candle_venda = (row["close"] < row["open"]) and (row["close"] < anterior["low"])

        rsi_compra = row["rsi"] > 50
        rsi_venda = row["rsi"] < 50

        sinal_compra = tendencia_alta and candle_compra and rsi_compra
        sinal_venda = tendencia_baixa and candle_venda and rsi_venda

        compra_forte = sinal_compra and (row["close"] > row["ema_fast"])
        venda_forte = sinal_venda and (row["close"] < row["ema_fast"])

        if not (compra_forte or venda_forte):
            continue

        risco_valor = equity * (risco_pct / 100)
        qty = risco_valor / row["atr"]

        if compra_forte:
            posicao = {
                "tipo": "compra",
                "entrada": row["close"],
                "sl": row["close"] - row["atr"],
                "tp": row["close"] + row["atr"] * 2,
                "qty": qty,
                "atr_entrada": row["atr"],
                "risco_valor": risco_valor,
            }
        else:
            posicao = {
                "tipo": "venda",
                "entrada": row["close"],
                "sl": row["close"] + row["atr"],
                "tp": row["close"] - row["atr"] * 2,
                "qty": qty,
                "atr_entrada": row["atr"],
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
    parser = argparse.ArgumentParser(description="Backtest multi-símbolo da estratégia Sniper Pro V7")
    parser.add_argument("--data-dir", required=True, help="pasta com um CSV por símbolo")
    parser.add_argument("--ema-rapida", type=int, default=9)
    parser.add_argument("--ema-lenta", type=int, default=21)
    parser.add_argument("--rsi-periodo", type=int, default=14)
    parser.add_argument("--atr-periodo", type=int, default=14)
    parser.add_argument("--risco-pct", type=float, default=1.0)
    parser.add_argument("--custo-pct-risco", type=float, default=5.0,
                         help="custo (comissão) por trade, como %% do valor arriscado na operação")
    parser.add_argument("--slippage-pct-atr", type=float, default=2.0,
                         help="slippage na saída, como %% do ATR da operação")
    parser.add_argument("--capital-inicial", type=float, default=1000.0)
    args = parser.parse_args()

    arquivos = sorted(glob.glob(os.path.join(args.data_dir, "*.csv")))
    if not arquivos:
        print(f"Nenhum CSV encontrado em {args.data_dir}")
        return

    resultados = []
    for caminho in arquivos:
        simbolo = os.path.splitext(os.path.basename(caminho))[0]
        try:
            df = carregar_csv(caminho)
            df = calcular_indicadores(df, args.ema_rapida, args.ema_lenta, args.rsi_periodo, args.atr_periodo)
            resultado = backtest_simbolo(df, args.risco_pct, args.custo_pct_risco, args.slippage_pct_atr, args.capital_inicial)
            resultado["simbolo"] = simbolo
            resultados.append(resultado)
        except Exception as e:
            print(f"Erro ao processar {simbolo}: {e}")

    if not resultados:
        print("Nenhum resultado gerado.")
        return

    colunas = ["simbolo", "trades", "win_rate_pct", "retorno_pct", "max_drawdown_pct", "fator_lucro"]
    largura = {c: max(len(c), max(len(str(r[c])) for r in resultados)) for c in colunas}

    cabecalho = " | ".join(c.ljust(largura[c]) for c in colunas)
    print(cabecalho)
    print("-" * len(cabecalho))
    for r in sorted(resultados, key=lambda x: x["retorno_pct"], reverse=True):
        print(" | ".join(str(r[c]).ljust(largura[c]) for c in colunas))


if __name__ == "__main__":
    main()
