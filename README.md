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

## Dashboard de monitoramento

```bash
python dashboard.py
# abre em http://127.0.0.1:8000
```

Mostra a curva de capital, últimos trades e últimas oportunidades detectadas,
lendo direto de `data/trades.csv` / `data/opportunities.csv`. É **somente
leitura**, sem autenticação e sem conceito de múltiplos usuários — uma janela
para acompanhar a sua própria conta, não uma plataforma para investidores
(ver a seção "Antes de pensar em captar capital de terceiros" abaixo). Por
isso ele escuta só em `127.0.0.1` por padrão; se mudar `--host` para algo
acessível pela rede, qualquer um que alcançar essa porta vê seus dados de
trading sem login.

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
ativo, monitore os logs de exposição não hedgeada, e leia a seção abaixo.

## Regulatório e fiscal no Brasil (leia antes de operar com dinheiro real)

**Isto não é aconselhamento jurídico ou contábil — é um ponto de partida.**
Fale com um contador especializado em criptoativos antes de operar com volume
relevante; as regras abaixo mudam com frequência.

### Você precisa de autorização do Banco Central?

A Lei 14.478/2022 (Marco Legal dos Criptoativos) e a regulamentação do Banco
Central exigem autorização para quem **presta serviço de ativos virtuais para
terceiros** (exchanges, custodiantes, corretoras). Rodar este bot **na sua
própria conta, com seu próprio capital**, não te torna uma prestadora de
serviços — você é usuário final de uma exchange que já deve ter essa
autorização (ou equivalente no exterior).

Isso muda completamente se você:
- operar com **dinheiro de terceiros** (amigos, "investidores", clientes) —
  isso te coloca na esfera de gestão de recursos/CVM e exige estrutura
  regulatória (ex: fundo de investimento, gestor autorizado) que este projeto
  **não** provê. Não use este bot para gerir capital de terceiros sem isso.
- oferecer o bot como serviço para outras pessoas operarem.

### Imposto de Renda

- **Ganho de capital, não "day trade" de bolsa**: criptoativos são tributados
  como bens/direitos (IN RFB 1.888/2019), não como renda variável de ações.
  Não existe alíquota fixa de "day trade" para cripto — cada alienação
  (venda, troca por outra moeda, etc.) é apurada como ganho de capital.
- **Isenção mensal de R$ 35.000**: se a soma de todas as vendas/alienações de
  criptoativos no mês for **até R$ 35.000**, o ganho é isento de IR. Acima
  disso, o ganho do mês inteiro é tributado (não só o excedente).
- **Alíquotas progressivas** sobre o ganho do mês: 15% até R$ 5 milhões,
  17,5% de R$ 5–10 milhões, 20% de R$ 10–30 milhões, 22,5% acima disso.
- **Apuração mensal obrigatória**: use o programa GCAP da Receita Federal
  para apurar o ganho de cada mês com operações tributáveis e pague o DARF
  até o último dia útil do mês seguinte. Arbitragem com várias operações por
  dia gera **muitas alienações por mês** — a apuração fica trabalhosa rápido;
  o `data/trades.csv` que o bot já gera ajuda a reconstruir o histórico, mas
  não substitui o cálculo de custo médio exigido pela Receita.
- **Declaração mensal de operações com criptoativos**: se a movimentação
  total do mês (em qualquer exchange, nacional ou estrangeira) passar de
  R$ 30.000, há obrigação de declarar essas operações à Receita Federal
  (IN RFB 1.888/2019), independente de ter dado lucro.
- **Declaração anual (DIRPF)**: declare o saldo de criptoativos na ficha de
  "Bens e Direitos" (códigos do grupo 08 — criptoativos), exchange por
  exchange/carteira por carteira.
- **Exchange estrangeira**: se usar uma exchange sem operação regulada no
  Brasil, há discussão em aberto sobre se o saldo lá se enquadra nas regras
  novas de tributação de "aplicações financeiras no exterior" (Lei
  14.754/2023) em vez do regime de ganho de capital padrão. Esse ponto **não
  é ainda totalmente assentado em normas/jurisprudência** — é exatamente o
  tipo de coisa que precisa de um contador para a sua situação específica.
- **Alta frequência pode virar "atividade empresarial"**: arbitragem
  automatizada rodando 24/7 com volume alto pode ser interpretada pela
  Receita como atividade habitual/profissional, sujeita a regras diferentes
  (possivelmente exigindo CNPJ e tributação de pessoa jurídica em vez de
  ganho de capital de pessoa física). Não há um limiar numérico oficial —
  outro ponto para validar com contador antes de escalar volume.

### Checklist mínimo antes de ligar o modo live

- [ ] Conta(s) de exchange com KYC completo e verificado.
- [ ] Conversa com contador especializado em criptoativos sobre seu caso.
- [ ] Processo definido para apurar e pagar DARF mensal (GCAP) caso ultrapasse
      R$ 35.000/mês em vendas.
- [ ] Decisão sobre declarar operações mensais à RFB se movimentação > R$ 30.000/mês.
- [ ] Confirmação de que está operando **só com capital próprio** (nunca de terceiros).
- [ ] Revisão anual da Declaração de Bens e Direitos incluindo os criptoativos.
