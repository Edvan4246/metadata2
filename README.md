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

## Execução real (opcional, desligada por padrão)

O módulo `arbitrage_bot/live_executor.py` implementa envio de ordens reais
(apenas para arbitragem **entre exchanges** — triangular permanece sempre em
paper trading nesta versão), mas fica travado por padrão. Para o bot enviar
qualquer ordem real, **três portões independentes** precisam estar ativos ao
mesmo tempo:

1. `live.enabled: true` em `config/settings.yaml`.
2. A flag `--live` na linha de comando.
3. A variável de ambiente `ARBITRAGE_BOT_LIVE_CONFIRM=I_UNDERSTAND_THE_RISK`.

Faltando qualquer um dos três, o bot roda 100% em paper trading.

### Gestão de chaves de API

- **Nunca em texto puro no config**: as chaves (`{EXCHANGE_ID}_API_KEY` /
  `{EXCHANGE_ID}_API_SECRET`, ex: `BINANCE_API_KEY`) só são lidas do
  ambiente — nunca do arquivo de configuração — então não há risco de
  comitar uma chave junto com `config/settings.yaml`.
- **Suporte a `.env`**: copie `.env.example` para `.env` e preencha; o bot
  carrega essas variáveis automaticamente ao iniciar
  (`arbitrage_bot.live_executor.load_env_file`). `.env` já está no
  `.gitignore` e uma variável já definida no ambiente do processo sempre tem
  prioridade sobre o que está no arquivo.
- **Chaves devem ser somente de negociação**: ao iniciar em modo live, o bot
  chama `AuthenticatedExchangeClient.assert_trade_only_permissions()`, que
  para Binance consulta as restrições reais da API key e **recusa subir** se
  detectar permissão de saque (withdrawal) habilitada. Para outras exchanges
  (sem endpoint equivalente ainda suportado aqui), o bot loga um aviso
  pedindo confirmação manual no painel da exchange — configure a chave sem
  permissão de saque por padrão, independente dessa checagem automática.

Proteções da execução real:

- **Sem retry automático de ordens**: um erro de rede ao criar uma ordem é
  ambíguo (pode ou não ter chegado na exchange); o bot nunca tenta de novo
  automaticamente, para não arriscar enviar a mesma ordem duas vezes
  (`AuthenticatedExchangeClient.create_market_order`).
- **Vende exatamente o que comprou**: a perna de venda usa o valor
  efetivamente preenchido na compra, nunca o valor pretendido original —
  protege contra overselling em caso de preenchimento parcial.
- **Aviso de exposição não hedgeada**: se a perna de venda preencher menos do
  que foi comprado, o bot loga um aviso explícito para intervenção manual em
  vez de assumir que está tudo certo.

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

Por padrão este projeto é um **detector + simulador**. A execução real (seção
acima) existe mas fica desligada até os três portões serem ativados
deliberadamente. Mesmo com ela ativada, arbitragem real em cripto tem riscos
que este código não resolve totalmente por si só:

- **Slippage residual**: mesmo com a validação por profundidade e ordens
  reais, ainda existe latência entre a leitura do book e o envio da ordem — o
  preço pode mudar nesse intervalo.
- **Triangular ainda não tem execução real**: nesta versão, só a arbitragem
  entre exchanges tem o caminho de ordens reais implementado; triangular
  permanece sempre em paper trading.
- **Custos não modelados**: taxas de saque/rede e limites de rate limit das
  exchanges.
- **Regulatório/KYC**: operar com dinheiro real em exchanges exige contas
  verificadas e conformidade com a regulamentação local.

Antes de operar com capital real de forma continuada, valide extensivamente em
paper trading, comece com tamanhos de trade pequenos mesmo com o modo live
ativo, monitore os logs de exposição não hedgeada, e faça validação
jurídica/fiscal para a sua jurisdição.
