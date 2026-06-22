//+------------------------------------------------------------------+
//|                                          SNIPER EDITION TRADER PRO V7 EA |
//+------------------------------------------------------------------+
#property copyright "Sniper Pro"
#property version   "1.10"
#property strict

#include <Trade\Trade.mqh>

input int    InpEmaRapida        = 9;
input int    InpEmaLenta         = 21;
input int    InpRsiPeriodo       = 14;
input int    InpAtrPeriodo       = 14;
input double InpRiskPercent      = 1.0;   // Risco por trade (% do equity)
input int    InpSlippagePoints   = 20;    // Slippage máximo aceito (em pontos)
input int    InpMagicNumber      = 778899;

input bool   InpFiltrarHorario   = true;  // Habilitar filtro de horário de sessão
input int    InpHoraInicio       = 8;     // Hora de início (horário do servidor)
input int    InpHoraFim          = 18;    // Hora de fim (horário do servidor)

input bool   InpFiltrarSpread    = true;  // Habilitar filtro de spread máximo
input int    InpSpreadMaximoPts  = 30;    // Spread máximo aceito (em pontos)

input bool   InpMostrarPainel    = true;  // Mostrar painel visual no gráfico

CTrade trade;

int emaFastHandle = INVALID_HANDLE;
int emaSlowHandle = INVALID_HANDLE;
int rsiHandle     = INVALID_HANDLE;
int atrHandle     = INVALID_HANDLE;

datetime lastBarTime = 0;

double gEmaFast = 0;
double gEmaSlow = 0;
double gRsi     = 0;
double gAtr     = 0;
string gStatus  = "AGUARDANDO";

#define PAINEL_PREFIXO "SniperProPainel_"

//+------------------------------------------------------------------+
int OnInit()
{
   emaFastHandle = iMA(_Symbol, _Period, InpEmaRapida, 0, MODE_EMA, PRICE_CLOSE);
   emaSlowHandle = iMA(_Symbol, _Period, InpEmaLenta, 0, MODE_EMA, PRICE_CLOSE);
   rsiHandle     = iRSI(_Symbol, _Period, InpRsiPeriodo, PRICE_CLOSE);
   atrHandle     = iATR(_Symbol, _Period, InpAtrPeriodo);

   if(emaFastHandle == INVALID_HANDLE || emaSlowHandle == INVALID_HANDLE ||
      rsiHandle == INVALID_HANDLE || atrHandle == INVALID_HANDLE)
      return INIT_FAILED;

   trade.SetExpertMagicNumber(InpMagicNumber);
   trade.SetDeviationInPoints((ulong)InpSlippagePoints);

   return INIT_SUCCEEDED;
}

//+------------------------------------------------------------------+
void OnDeinit(const int reason)
{
   IndicatorRelease(emaFastHandle);
   IndicatorRelease(emaSlowHandle);
   IndicatorRelease(rsiHandle);
   IndicatorRelease(atrHandle);
   ObjectsDeleteAll(0, PAINEL_PREFIXO);
}

//+------------------------------------------------------------------+
bool PossuiPosicao(ENUM_POSITION_TYPE tipo)
{
   for(int i = 0; i < PositionsTotal(); i++)
   {
      ulong ticket = PositionGetTicket(i);
      if(ticket == 0) continue;
      if(PositionGetString(POSITION_SYMBOL) != _Symbol) continue;
      if(PositionGetInteger(POSITION_MAGIC) != InpMagicNumber) continue;
      if((ENUM_POSITION_TYPE)PositionGetInteger(POSITION_TYPE) == tipo) return true;
   }
   return false;
}

void FecharPosicaoContraria(ENUM_POSITION_TYPE tipoContrario)
{
   for(int i = PositionsTotal() - 1; i >= 0; i--)
   {
      ulong ticket = PositionGetTicket(i);
      if(ticket == 0) continue;
      if(PositionGetString(POSITION_SYMBOL) != _Symbol) continue;
      if(PositionGetInteger(POSITION_MAGIC) != InpMagicNumber) continue;
      if((ENUM_POSITION_TYPE)PositionGetInteger(POSITION_TYPE) == tipoContrario)
         trade.PositionClose(ticket);
   }
}

//+------------------------------------------------------------------+
// Janela de horário (suporta intervalo que cruza a meia-noite, ex: 22h-6h)
bool DentroHorario()
{
   if(!InpFiltrarHorario) return true;

   MqlDateTime dt;
   TimeToStruct(TimeCurrent(), dt);
   int hora = dt.hour;

   if(InpHoraInicio <= InpHoraFim)
      return (hora >= InpHoraInicio && hora < InpHoraFim);

   return (hora >= InpHoraInicio || hora < InpHoraFim);
}

bool SpreadOk()
{
   if(!InpFiltrarSpread) return true;
   long spreadAtual = SymbolInfoInteger(_Symbol, SYMBOL_SPREAD);
   return spreadAtual <= InpSpreadMaximoPts;
}

//+------------------------------------------------------------------+
// Lote calculado para que a distância até o stop (slDistance, em preço)
// represente exatamente InpRiskPercent do equity atual.
double CalcularLote(double slDistance)
{
   if(slDistance <= 0) return 0;

   double riskAmount = AccountInfoDouble(ACCOUNT_EQUITY) * (InpRiskPercent / 100.0);

   double tickValue = SymbolInfoDouble(_Symbol, SYMBOL_TRADE_TICK_VALUE);
   double tickSize  = SymbolInfoDouble(_Symbol, SYMBOL_TRADE_TICK_SIZE);
   if(tickValue <= 0 || tickSize <= 0) return 0;

   double valuePerPriceUnit = tickValue / tickSize;
   double lots = riskAmount / (slDistance * valuePerPriceUnit);

   double lotStep = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_STEP);
   double minLot  = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MIN);
   double maxLot  = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MAX);

   lots = MathFloor(lots / lotStep) * lotStep;
   lots = MathMax(minLot, MathMin(maxLot, lots));

   return lots;
}

void AbrirCompra(double sl, double tp, double slDistance)
{
   if(!DentroHorario() || !SpreadOk()) return;

   FecharPosicaoContraria(POSITION_TYPE_SELL);
   if(PossuiPosicao(POSITION_TYPE_BUY)) return;

   double lots = CalcularLote(slDistance);
   if(lots <= 0) return;

   double price = SymbolInfoDouble(_Symbol, SYMBOL_ASK);
   trade.Buy(lots, _Symbol, price, sl, tp, "Sniper Pro Compra");
}

void AbrirVenda(double sl, double tp, double slDistance)
{
   if(!DentroHorario() || !SpreadOk()) return;

   FecharPosicaoContraria(POSITION_TYPE_BUY);
   if(PossuiPosicao(POSITION_TYPE_SELL)) return;

   double lots = CalcularLote(slDistance);
   if(lots <= 0) return;

   double price = SymbolInfoDouble(_Symbol, SYMBOL_BID);
   trade.Sell(lots, _Symbol, price, sl, tp, "Sniper Pro Venda");
}

//+------------------------------------------------------------------+
void CriarOuAtualizarLabel(string nomeSufixo, string texto, int y, color cor)
{
   string nome = PAINEL_PREFIXO + nomeSufixo;
   if(ObjectFind(0, nome) < 0)
   {
      ObjectCreate(0, nome, OBJ_LABEL, 0, 0, 0);
      ObjectSetInteger(0, nome, OBJPROP_CORNER, CORNER_RIGHT_UPPER);
      ObjectSetInteger(0, nome, OBJPROP_XDISTANCE, 12);
      ObjectSetInteger(0, nome, OBJPROP_FONTSIZE, 9);
      ObjectSetString(0, nome, OBJPROP_FONT, "Consolas");
   }
   ObjectSetInteger(0, nome, OBJPROP_YDISTANCE, y);
   ObjectSetString(0, nome, OBJPROP_TEXT, texto);
   ObjectSetInteger(0, nome, OBJPROP_COLOR, cor);
}

void AtualizarPainel()
{
   if(!InpMostrarPainel) return;

   color verde    = clrLime;
   color vermelho = clrRed;
   color azul     = clrDeepSkyBlue;
   color branco   = clrWhite;

   bool tendenciaAlta = gEmaFast > gEmaSlow;
   long spreadAtual    = SymbolInfoInteger(_Symbol, SYMBOL_SPREAD);

   CriarOuAtualizarLabel("titulo",   "SNIPER PRO EA - ONLINE",                         18,  verde);
   CriarOuAtualizarLabel("tend",     "Tendência: " + (tendenciaAlta ? "ALTA" : "BAIXA"), 36,  tendenciaAlta ? verde : vermelho);
   CriarOuAtualizarLabel("rsi",      "RSI: " + DoubleToString(gRsi, 1),                 54,  azul);
   CriarOuAtualizarLabel("atr",      "ATR: " + DoubleToString(gAtr, _Digits),           72,  azul);
   CriarOuAtualizarLabel("spread",   "Spread: " + IntegerToString(spreadAtual) + " pts" +
                                      (SpreadOk() ? "" : " (ALTO)"),                     90,  SpreadOk() ? branco : vermelho);
   CriarOuAtualizarLabel("horario",  "Sessão: " + (DentroHorario() ? "LIBERADA" : "FORA DA JANELA"), 108, DentroHorario() ? verde : vermelho);
   CriarOuAtualizarLabel("status",   "Status: " + gStatus,                              126,
                                      gStatus == "COMPRA" ? verde : (gStatus == "VENDA" ? vermelho : azul));
}

//+------------------------------------------------------------------+
void OnTick()
{
   AtualizarPainel();

   datetime currentBarTime = iTime(_Symbol, _Period, 0);
   if(currentBarTime == lastBarTime) return;
   lastBarTime = currentBarTime;

   if(Bars(_Symbol, _Period) < InpEmaLenta + 5) return;

   double emaFastBuf[1], emaSlowBuf[1], rsiBuf[1], atrBuf[1];
   if(CopyBuffer(emaFastHandle, 0, 1, 1, emaFastBuf) <= 0) return;
   if(CopyBuffer(emaSlowHandle, 0, 1, 1, emaSlowBuf) <= 0) return;
   if(CopyBuffer(rsiHandle, 0, 1, 1, rsiBuf) <= 0) return;
   if(CopyBuffer(atrHandle, 0, 1, 1, atrBuf) <= 0) return;

   double emaFast  = emaFastBuf[0];
   double emaSlow  = emaSlowBuf[0];
   double rsiValor = rsiBuf[0];
   double atrValor = atrBuf[0];

   gEmaFast = emaFast;
   gEmaSlow = emaSlow;
   gRsi     = rsiValor;
   gAtr     = atrValor;

   // Shift 1 = última barra fechada (equivalente ao barstate.isconfirmed do Pine)
   double closeConfirmada = iClose(_Symbol, _Period, 1);
   double openConfirmada  = iOpen(_Symbol, _Period, 1);
   double highAnterior    = iHigh(_Symbol, _Period, 2);
   double lowAnterior     = iLow(_Symbol, _Period, 2);

   bool tendenciaAlta  = emaFast > emaSlow;
   bool tendenciaBaixa = emaFast < emaSlow;

   bool candleCompra = (closeConfirmada > openConfirmada) && (closeConfirmada > highAnterior);
   bool candleVenda  = (closeConfirmada < openConfirmada) && (closeConfirmada < lowAnterior);

   bool rsiCompra = rsiValor > 50;
   bool rsiVenda  = rsiValor < 50;

   bool sinalCompra = tendenciaAlta && candleCompra && rsiCompra;
   bool sinalVenda  = tendenciaBaixa && candleVenda && rsiVenda;

   bool compraForte = sinalCompra && (closeConfirmada > emaFast);
   bool vendaForte  = sinalVenda && (closeConfirmada < emaFast);

   gStatus = compraForte ? "COMPRA" : (vendaForte ? "VENDA" : "AGUARDANDO");

   double buyTP  = closeConfirmada + atrValor * 2;
   double buySL  = closeConfirmada - atrValor;
   double sellTP = closeConfirmada - atrValor * 2;
   double sellSL = closeConfirmada + atrValor;

   if(compraForte)
      AbrirCompra(buySL, buyTP, atrValor);

   if(vendaForte)
      AbrirVenda(sellSL, sellTP, atrValor);
}
