//+------------------------------------------------------------------+
//|                                          SNIPER EDITION TRADER PRO V7 EA |
//+------------------------------------------------------------------+
#property copyright "Sniper Pro"
#property version   "1.00"
#property strict

#include <Trade\Trade.mqh>

input int    InpEmaRapida       = 9;
input int    InpEmaLenta        = 21;
input int    InpRsiPeriodo      = 14;
input int    InpAtrPeriodo      = 14;
input double InpRiskPercent     = 1.0;   // Risco por trade (% do equity)
input int    InpSlippagePoints  = 20;    // Slippage máximo aceito (em pontos)
input int    InpMagicNumber     = 778899;

CTrade trade;

int emaFastHandle = INVALID_HANDLE;
int emaSlowHandle = INVALID_HANDLE;
int rsiHandle     = INVALID_HANDLE;
int atrHandle     = INVALID_HANDLE;

datetime lastBarTime = 0;

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
   FecharPosicaoContraria(POSITION_TYPE_SELL);
   if(PossuiPosicao(POSITION_TYPE_BUY)) return;

   double lots = CalcularLote(slDistance);
   if(lots <= 0) return;

   double price = SymbolInfoDouble(_Symbol, SYMBOL_ASK);
   trade.Buy(lots, _Symbol, price, sl, tp, "Sniper Pro Compra");
}

void AbrirVenda(double sl, double tp, double slDistance)
{
   FecharPosicaoContraria(POSITION_TYPE_BUY);
   if(PossuiPosicao(POSITION_TYPE_SELL)) return;

   double lots = CalcularLote(slDistance);
   if(lots <= 0) return;

   double price = SymbolInfoDouble(_Symbol, SYMBOL_BID);
   trade.Sell(lots, _Symbol, price, sl, tp, "Sniper Pro Venda");
}

//+------------------------------------------------------------------+
void OnTick()
{
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

   double buyTP  = closeConfirmada + atrValor * 2;
   double buySL  = closeConfirmada - atrValor;
   double sellTP = closeConfirmada - atrValor * 2;
   double sellSL = closeConfirmada + atrValor;

   if(compraForte)
      AbrirCompra(buySL, buyTP, atrValor);

   if(vendaForte)
      AbrirVenda(sellSL, sellTP, atrValor);
}
