# Bot de Arbitragem Cripto (Paper Trading)

Sistema para **detectar** oportunidades de arbitragem no mercado de criptomoedas
(triangular e entre exchanges), com foco em **proteção de capital**. Por padrão
o bot roda em **paper trading**: ele lê apenas dados públicos de mercado (via
[ccxt](https://github.com/ccxt/ccxt)) e simula as execuções — nenhuma chave de
API de negociação é usada e nenhuma ordem real é enviada.

## Por que é seguro por padrão

- **Sem chaves de API / sem ordens reais**: `ExchangeClient` só usa endpoints
  públicos (`fetch_tickers`). Não há método de envio de ordem em todo o código.
- **Capital virtual**: `RiskManager` opera sobre um saldo simulado
  (`risk.initial_capital`), nunca toca uma conta real.
- **Lucro líquido de taxas**: cada oportunidade já desconta a taxa taker
  (`risk.taker_fee_pct`) em cada perna da operação antes de decidir se vale a pena.
- **Limite de exposição por operação**: no máximo `risk.max_trade_pct` do
  capital atual por trade.
- **Piso mínimo de lucro**: só opera se o lucro líquido estimado for
  `>= risk.min_profit_pct`.
- **Circuit breaker diário**: se a perda acumulada no dia atingir
  `risk.max_daily_loss_pct`, o bot trava novas operações até o dia seguinte.
- **Log de tudo**: toda oportunidade detectada (`data/opportunities.csv`) e todo
  trade simulado (`data/trades.csv`) ficam registrados para auditoria.
- **Validação por profundidade do livro de ofertas**: o scan inicial usa
  bid/ask (rápido, leve) só para achar candidatos. Antes de qualquer trade,
  o bot busca o order book real dos pares envolvidos e recalcula o lucro
  líquido simulando o preenchimento da ordem pelos níveis de profundidade
  reais (`arbitrage_bot/depth_check.py`). Se a liquidez não suportar o
  tamanho do trade, a oportunidade é descartada em vez de assumir que o
  bid/ask aguenta o volume todo.
- **Capital pré-posicionado por exchange**: para arbitragem entre exchanges, o
  bot só negocia o quanto o `cross_exchange.allocation` de cada exchange
  realmente suporta (`arbitrage_bot/balances.py`) — nunca assume que dá para
  transferir fundos durante a janela da oportunidade. Cada trade desloca o
  saldo entre as exchanges, e um aviso é logado quando alguma moeda cai abaixo
  de `rebalance_warning_pct` do alocado, sinalizando que é hora de transferir
  fundos manualmente para rebalancear.

## Instalação

```bash
pip install -r requirements.txt
```

## Configuração

Edite `config/settings.yaml`:

- `exchange.id`: exchange principal (id do ccxt) usada para a arbitragem triangular.
- `triangular.alt_currencies`: moedas usadas para montar os triângulos `BASE -> X -> Y -> BASE`.
- `cross_exchange.exchanges`: lista de exchanges (ids do ccxt) comparadas entre si.
  Com apenas uma exchange na lista, o detector fica ativo mas nunca encontra
  oportunidades (precisa de duas ou mais exchanges cotando o mesmo par).
- `cross_exchange.allocation`: capital pré-posicionado em cada exchange (por
  moeda). Sem isso, trades cross-exchange nunca são executados — ver seção
  acima. `rebalance_warning_pct` controla quando o bot avisa que é hora de
  transferir fundos entre exchanges.
- `risk.*`: parâmetros de proteção de capital descritos acima.
- `loop.interval_seconds`: intervalo entre cada rodada de checagem.

## Uso

```bash
# loop contínuo
python main.py

# uma única iteração (útil para testes/cron)
python main.py --once

# configuração alternativa
python main.py --config minha_config.yaml
```

## Testes

```bash
pytest
```

## Limitações importantes (leia antes de ir para produção)

Este projeto é um **detector + simulador**, não um executor de ordens reais.
Arbitragem real em cripto tem riscos que este código *não* resolve por si só:

- **Execução real**: mesmo com a validação por profundidade, ordens reais podem
  ter preenchimento parcial ou latência entre a leitura do book e o envio da
  ordem — o preço pode mudar nesse intervalo, então a validação reduz mas não
  elimina o risco de slippage.
- **Custos não modelados**: taxas de saque/rede e limites de rate limit das
  exchanges.
- **Regulatório/KYC**: operar com dinheiro real em exchanges exige contas
  verificadas e conformidade com a regulamentação local.

Antes de conectar isso a uma conta real, adicione: execução real com
tratamento de erros e ordens parciais, gestão segura de chaves de API (nunca
em texto puro), depósitos reais que correspondam ao `allocation` configurado,
testes extensos em paper trading, e validação jurídica/fiscal.
