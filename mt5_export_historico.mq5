//+------------------------------------------------------------------+
//|                                    Sniper Pro - Exportar Histórico CSV |
//+------------------------------------------------------------------+
#property script_show_inputs

input string InpSimbolos          = "EURUSD,GBPUSD,USDJPY,XAUUSD,XAGUSD";
input ENUM_TIMEFRAMES InpTimeframe = PERIOD_H1;
input int InpBarras                = 5000;

void OnStart()
{
   string simbolos[];
   int total = StringSplit(InpSimbolos, ',', simbolos);

   for(int s = 0; s < total; s++)
   {
      string simbolo = simbolos[s];
      StringTrimLeft(simbolo);
      StringTrimRight(simbolo);

      if(!SymbolSelect(simbolo, true))
      {
         Print("Símbolo não encontrado: ", simbolo);
         continue;
      }

      MqlRates rates[];
      int copiados = CopyRates(simbolo, InpTimeframe, 0, InpBarras, rates);
      if(copiados <= 0)
      {
         Print("Falha ao copiar histórico de ", simbolo, " - erro ", GetLastError());
         continue;
      }

      int digitos = (int)SymbolInfoInteger(simbolo, SYMBOL_DIGITS);
      string nomeArquivo = simbolo + "_" + EnumToString(InpTimeframe) + ".csv";

      int handle = FileOpen(nomeArquivo, FILE_WRITE | FILE_CSV | FILE_ANSI, ',');
      if(handle == INVALID_HANDLE)
      {
         Print("Falha ao criar arquivo para ", simbolo, " - erro ", GetLastError());
         continue;
      }

      FileWrite(handle, "time", "open", "high", "low", "close", "volume");
      for(int i = 0; i < copiados; i++)
      {
         FileWrite(handle,
            TimeToString(rates[i].time, TIME_DATE | TIME_MINUTES),
            DoubleToString(rates[i].open, digitos),
            DoubleToString(rates[i].high, digitos),
            DoubleToString(rates[i].low, digitos),
            DoubleToString(rates[i].close, digitos),
            (long)rates[i].tick_volume);
      }
      FileClose(handle);
      Print("Exportado: ", nomeArquivo, " (", copiados, " barras)");
   }

   Print("Concluído. Os arquivos ficam em MQL5/Files (Arquivo > Abrir pasta de dados).");
}
