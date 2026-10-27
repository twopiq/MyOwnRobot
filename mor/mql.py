"""MetaTrader 5 uchun yordamchi MQL5 skriptlar (ilova ularni faylga saqlab beradi)."""

CALENDAR_SCRIPT = r'''//+------------------------------------------------------------------+
//| ExportCalendar.mq5 — MyOwnRobot uchun iqtisodiy kalendar eksporti  |
//| Natija: MQL5/Files/calendar.csv  (time,currency,impact,title,...)  |
//| Vaqt — TERMINAL (server) vaqtida yoziladi, MT5 shamlari bilan bir xil |
//+------------------------------------------------------------------+
#property script_show_inputs
input datetime InpFrom          = D'2022.01.01'; // boshlanish
input datetime InpTo            = 0;             // tugash (0 = hozir)
input int      InpMinImportance = 2;             // 1 past, 2 o'rta, 3 yuqori
input string   InpFile          = "calendar.csv";

string Clean(string s)
  {
   StringReplace(s, ",", " ");
   StringReplace(s, ";", " ");
   StringReplace(s, "\"", "'");
   return s;
  }

string Num(const MqlCalendarValue &v, const int which)
  {
   if(which == 0) return v.HasActualValue()   ? DoubleToString(v.GetActualValue(), 4)   : "";
   if(which == 1) return v.HasForecastValue() ? DoubleToString(v.GetForecastValue(), 4) : "";
   return v.HasPreviousValue() ? DoubleToString(v.GetPreviousValue(), 4) : "";
  }

void OnStart()
  {
   datetime to = (InpTo == 0) ? TimeCurrent() : InpTo;
   MqlCalendarValue vals[];
   int n = CalendarValueHistory(vals, InpFrom, to);
   if(n <= 0)
     {
      Print("Kalendar bo'sh yoki mavjud emas, xato: ", GetLastError(),
            ". Terminalda Kalendar (Ctrl+T -> Kalendar) yuklanganini tekshiring.");
      return;
     }
   int h = FileOpen(InpFile, FILE_WRITE | FILE_CSV | FILE_ANSI, ',', CP_UTF8);
   if(h == INVALID_HANDLE)
     {
      Print("Fayl ochilmadi: ", InpFile, " xato ", GetLastError());
      return;
     }
   FileWrite(h, "time", "currency", "impact", "title", "actual", "forecast", "previous");
   int written = 0;
   for(int i = 0; i < n; i++)
     {
      MqlCalendarEvent ev;
      if(!CalendarEventById(vals[i].event_id, ev)) continue;
      if((int)ev.importance < InpMinImportance) continue;
      MqlCalendarCountry c;
      if(!CalendarCountryById(ev.country_id, c)) continue;
      FileWrite(h, TimeToString(vals[i].time, TIME_DATE | TIME_MINUTES), c.currency,
                (int)ev.importance, Clean(ev.name), Num(vals[i], 0), Num(vals[i], 1), Num(vals[i], 2));
      written++;
     }
   FileClose(h);
   PrintFormat("Tayyor: %d voqea -> MQL5/Files/%s (Fayl -> Ma'lumotlar papkasini ochish)", written, InpFile);
  }
'''
