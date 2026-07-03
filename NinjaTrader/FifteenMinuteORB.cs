#region Using declarations
using System;
using System.Collections.Generic;
using System.ComponentModel;
using System.ComponentModel.DataAnnotations;
using System.Linq;
using System.Windows.Media;
using NinjaTrader.Cbi;
using NinjaTrader.Data;
using NinjaTrader.Gui.Tools;
using NinjaTrader.NinjaScript;
using NinjaTrader.Core.FloatingPoint;
#endregion

// ============================================================================
//  FifteenMinuteORB  (v1.1)  -  Opening Range Breakout for index futures
//                               (MNQ / MES / NQ / ES)
//
//  v1.1 (2026-07-03): added daily DECISION LOGGING to the NinjaScript Output
//    window. Every session prints one line -- either why it stood down
//    (width / ADX / ATR-warmup / VWAP-slope bias) or that it armed, with the
//    entry / stop / target levels. NO change to trading logic or numbers; the
//    only code added is Print() calls + two "printed once" guard flags.
//
//  NAME NOTE: this was formerly "FiveMinuteORB" -- a leftover from when the
//  project started as a 5-minute range. The champion is a 15-MINUTE ORB, so the
//  class is renamed to match. (C# won't allow "15 Min ORB" as a class name --
//  identifiers can't start with a digit or contain spaces -- so FifteenMinuteORB
//  is the valid equivalent. The version shows as "FifteenMinuteORB v1.1" in the
//  strategy list; the class name is kept stable so a chart's attached strategy
//  survives recompiles.)
//
//  This is the PORT of the optimized Python engine. It reproduces the winning
//  config from the 7-year MNQ study, on POST-AUDIT clean data (2026-07-02):
//
//      OR 15 min | offset 2 ticks | both directions | vwap_slope bias
//      width <= 130 pts | ADX regime (>=20) | ATR 1.5x target
//      -> 836 trades, net ~$27,025/7yr/micro, PF 1.44, win 44.1%,
//         maxDD -$1,769 (fits the 50K account's $2,000 limit)
//
//  RULES
//    1. Mark the High/Low of the first OrMinutes after the cash open = the OR.
//    2. WIDTH FILTER: skip the day if (orHigh - orLow) > MaxOrPoints.
//    3. ADX REGIME: skip the day unless yesterday's daily ADX(14) >= AdxMin.
//    4. VWAP_SLOPE BIAS: take only the trend-side breakout -- if the running
//       session VWAP rose across the OR, trade LONG only; if it fell, SHORT only.
//    5. ENTRY: buy-stop at OR high + offset / sell-stop at OR low - offset; first
//       touch fills, the other order is cancelled (manual OCO).
//    6. STOP: the opposite OR extreme (-/+ offset).
//    7. TARGET: TargetMode=Atr -> entry +/- TargetAtrMult * yesterday's daily ATR;
//               TargetMode=RewardRisk -> entry +/- RewardRiskRatio * risk.
//    8. One trade/day; flatten before the close.
//
//  PARITY NOTES (read before forward-testing against the Python backtest):
//    * Run on a 1-MINUTE chart, Calculate.OnBarClose.
//    * The daily bars (for ATR/ADX) and the session VWAP are built INTERNALLY by
//      aggregating the primary 1-min bars per calendar day, starting at
//      DailyAggStartTime (default 08:00, matching the CSV export which begins at
//      08:00 ET). Set DailyAggStartTime to wherever YOUR data feed's day begins so
//      the daily H/L/C and VWAP match the backtest. Use the SAME instrument +
//      session template you exported the CSV with.
//    * ATR/ADX use Wilder smoothing identical to the Python _atr/_adx, computed on
//      the prior COMPLETED day (no lookahead). They need warmup (ATR ~15 days,
//      ADX ~29 days) before any trade is taken.
// ============================================================================

namespace NinjaTrader.NinjaScript.Strategies
{
	public enum OrbBiasMode { None, VwapSlope }
	public enum OrbTargetMode { RewardRisk, Atr }

	public class FifteenMinuteORB : Strategy
	{
		// --- per-day OR state ------------------------------------------------
		private double		orHigh;
		private double		orLow;
		private bool		orComplete;
		private DateTime	currentDay;
		private DateTime	orStartDt;
		private DateTime	orEndDt;
		private int			tradesToday;
		private Order		longEntry;
		private Order		shortEntry;

		// --- per-day directional gate (set at OR close) ----------------------
		private bool		dayAllowLong;
		private bool		dayAllowShort;
		private bool		dayTradeable;
		private bool		ordersLoggedToday;   // v1.1: arm-levels line printed once/day
		private bool		startupLogged;       // v1.1: startup banner printed once

		// --- internal daily-bar accumulation (for ATR / ADX) -----------------
		private readonly List<double> dH = new List<double>();
		private readonly List<double> dL = new List<double>();
		private readonly List<double> dC = new List<double>();
		private double		dayHi, dayLo, dayCl;
		private bool		haveDay;
		private double		atrPrev;   // Wilder ATR through the prior completed day (NaN until warm)
		private double		adxPrev;   // Wilder ADX through the prior completed day (NaN until warm)

		// --- internal session VWAP accumulation (for vwap_slope bias) --------
		private double		cumVP;     // sum(typical_price * volume) from day start
		private double		cumV;      // sum(volume) from day start
		private double		vwapStart; // running VWAP captured at the first OR bar
		private bool		vwapStartCaptured;

		protected override void OnStateChange()
		{
			if (State == State.SetDefaults)
			{
				Description					= "Optimized 15-minute Opening Range Breakout (vwap_slope bias + ADX regime + width filter + ATR target). Port of the 7-year MNQ winning config. v1.1: daily decision logging to the Output window.";
				Name						= "FifteenMinuteORB v1.1";

				Calculate					= Calculate.OnBarClose;
				EntriesPerDirection			= 1;
				EntryHandling				= EntryHandling.AllEntries;
				IsExitOnSessionCloseStrategy= true;
				ExitOnSessionCloseSeconds	= 30;
				BarsRequiredToTrade			= 1;

				// ---- defaults = the winning config ----
				OrStartTime					= 93000;	// 09:30:00 cash open
				OrMinutes					= 15;		// 15-minute opening range
				ExitTime					= 155500;	// 15:55:00 force-flat
				BreakoutOffsetTicks			= 2;		// entry/stop offset
				Quantity					= 1;		// 1 micro per account (cycle-safe sizing)
				MaxTradesPerDay				= 1;
				EnableLong					= true;
				EnableShort					= true;

				MaxOrPoints					= 130.0;	// width filter (0 = off)
				Bias						= OrbBiasMode.VwapSlope;
				UseAdxRegime				= true;
				AdxMin						= 20.0;
				AdxPeriod					= 14;

				TargetMode					= OrbTargetMode.Atr;
				TargetAtrMult				= 1.5;
				AtrPeriod					= 14;
				RewardRiskRatio				= 1.0;		// only used when TargetMode = RewardRisk

				DailyAggStartTime			= 80000;	// 08:00:00 -- where each day's data/feed begins
				DailyAggEndTime				= 170000;	// 17:00:00 -- where each day's data/feed ends (keeps overnight out)
			}
			else if (State == State.DataLoaded)
			{
				currentDay	= DateTime.MinValue;
				atrPrev		= double.NaN;
				adxPrev		= double.NaN;
				haveDay		= false;
			}
		}

		protected override void OnBarUpdate()
		{
			if (BarsInProgress != 0)				return;
			if (CurrentBar < BarsRequiredToTrade)	return;

			int now = ToTime(Time[0]);				// HHmmss

			// v1.1: one-time banner so you can see the strategy is live in the Output window
			if (!startupLogged)
			{
				Print("FifteenMinuteORB v1.1 active on " + Instrument.FullName
					+ " -- one line prints per session (trade or skip reason).");
				startupLogged = true;
			}

			// ---- 1) New trading day --------------------------------------------
			if (Time[0].Date != currentDay)
			{
				// finalize YESTERDAY's daily bar and roll the Wilder ATR/ADX
				if (haveDay)
				{
					dH.Add(dayHi); dL.Add(dayLo); dC.Add(dayCl);
					atrPrev = WilderAtrLast(dH, dL, dC, AtrPeriod);
					adxPrev = WilderAdxLast(dH, dL, dC, AdxPeriod);
				}

				currentDay	= Time[0].Date;
				orHigh		= double.MinValue;
				orLow		= double.MaxValue;
				orComplete	= false;
				tradesToday	= 0;
				dayAllowLong = dayAllowShort = dayTradeable = false;
				ordersLoggedToday = false;

				CancelIfWorking(longEntry);
				CancelIfWorking(shortEntry);
				longEntry	= null;
				shortEntry	= null;

				orStartDt = currentDay.AddHours(OrStartTime / 10000)
									  .AddMinutes((OrStartTime / 100) % 100)
									  .AddSeconds(OrStartTime % 100);
				orEndDt   = orStartDt.AddMinutes(OrMinutes);

				// reset the daily-bar and VWAP accumulators for the new day
				haveDay			= false;
				cumVP = cumV	= 0.0;
				vwapStart		= double.NaN;
				vwapStartCaptured = false;
			}

			// ---- 2) Accumulate the internal daily bar + session VWAP -----------
			// Bound to the (DailyAggStartTime, DailyAggEndTime] window so the daily
			// H/L/C and VWAP match the Python engine's per-day data exactly (the CSV
			// covers 08:00->17:00 ET). The end bound is what keeps the overnight Globex
			// session out of the daily bar. Bars are END-stamped (NT default), so a bar
			// stamped 08:01 covers 08:00-08:01 (included) and one stamped 08:00 covers
			// 07:59-08:00 (excluded) -- hence '>' on start, '<=' on end.
			if (now > DailyAggStartTime && now <= DailyAggEndTime)
			{
				if (!haveDay)
				{
					dayHi = High[0]; dayLo = Low[0]; dayCl = Close[0];
					haveDay = true;
				}
				else
				{
					if (High[0] > dayHi) dayHi = High[0];
					if (Low[0]  < dayLo) dayLo = Low[0];
					dayCl = Close[0];
				}

				double tp = (High[0] + Low[0] + Close[0]) / 3.0;
				cumVP += tp * Volume[0];
				cumV  += Volume[0];
			}

			// ---- 3) After the flatten time: stand down -------------------------
			if (now >= ExitTime)
			{
				CancelIfWorking(longEntry);
				CancelIfWorking(shortEntry);
				if (Position.MarketPosition == MarketPosition.Long)			ExitLong();
				else if (Position.MarketPosition == MarketPosition.Short)	ExitShort();
				return;
			}

			// ---- 4) Before the opening range starts: nothing to trade ----------
			if (Time[0] <= orStartDt) return;

			// ---- 5) Build the opening range ------------------------------------
			if (!orComplete)
			{
				if (Time[0] <= orEndDt)
				{
					orHigh = Math.Max(orHigh, High[0]);
					orLow  = Math.Min(orLow,  Low[0]);

					// capture the running VWAP at the first OR bar (= Python vws[si])
					if (!vwapStartCaptured && cumV > 0)
					{
						vwapStart = cumVP / cumV;
						vwapStartCaptured = true;
					}
				}

				if (Time[0] >= orEndDt)
				{
					orComplete = orHigh > orLow;
					if (orComplete)
						EvaluateDayFilters();		// width / ADX / vwap_slope -> set the day's gate
				}

				if (!orComplete)
					return;
				// else fall through and arm on this same bar
			}

			// ---- 6) Day filtered out? -> no orders today -----------------------
			if (!dayTradeable)
			{
				CancelIfWorking(longEntry);
				CancelIfWorking(shortEntry);
				return;
			}

			// ---- 7) Trade the breakout -----------------------------------------
			if (tradesToday >= MaxTradesPerDay)
			{
				CancelIfWorking(longEntry);
				CancelIfWorking(shortEntry);
				return;
			}

			if (Position.MarketPosition == MarketPosition.Flat)
			{
				double offset = BreakoutOffsetTicks * TickSize;

				if (EnableLong && dayAllowLong)
				{
					double entryL  = RoundTick(orHigh + offset);
					double stopL   = RoundTick(orLow  - offset);
					double targetL = ComputeTarget(entryL, stopL, true);
					if (!double.IsNaN(targetL))
					{
						SetStopLoss("ORlong",     CalculationMode.Price, stopL,   false);
						SetProfitTarget("ORlong", CalculationMode.Price, targetL);
						longEntry = EnterLongStopMarket(0, true, Quantity, entryL, "ORlong");
						if (!ordersLoggedToday)
							Print(currentDay.ToString("yyyy-MM-dd") + "  ARM LONG   buy-stop " + entryL
								+ "  stop " + stopL + "  target " + targetL.ToString("F2"));
					}
				}

				if (EnableShort && dayAllowShort)
				{
					double entryS  = RoundTick(orLow  - offset);
					double stopS   = RoundTick(orHigh + offset);
					double targetS = ComputeTarget(entryS, stopS, false);
					if (!double.IsNaN(targetS))
					{
						SetStopLoss("ORshort",     CalculationMode.Price, stopS,   false);
						SetProfitTarget("ORshort", CalculationMode.Price, targetS);
						shortEntry = EnterShortStopMarket(0, true, Quantity, entryS, "ORshort");
						if (!ordersLoggedToday)
							Print(currentDay.ToString("yyyy-MM-dd") + "  ARM SHORT  sell-stop " + entryS
								+ "  stop " + stopS + "  target " + targetS.ToString("F2"));
					}
				}

				ordersLoggedToday = true;
			}
			else
			{
				if (Position.MarketPosition == MarketPosition.Long)			CancelIfWorking(shortEntry);
				else if (Position.MarketPosition == MarketPosition.Short)	CancelIfWorking(longEntry);
			}
		}

		// Decide whether today is tradeable and which side(s) the bias allows.
		// Mirrors the Python run_prepared gate order: width -> regime -> bias.
		// v1.1: every branch prints its decision to the Output window.
		private void EvaluateDayFilters()
		{
			dayTradeable = false;
			dayAllowLong = EnableLong;
			dayAllowShort = EnableShort;

			string tag = currentDay.ToString("yyyy-MM-dd") + "  ";
			double widthPts = orHigh - orLow;

			// width filter
			if (MaxOrPoints > 0 && widthPts > MaxOrPoints)
			{
				Print(tag + "SKIP   OR width " + widthPts.ToString("F1") + " pts > " + MaxOrPoints.ToString("F0") + " limit");
				return;
			}

			// ADX regime (prior completed day)
			if (UseAdxRegime)
			{
				if (double.IsNaN(adxPrev))
				{
					Print(tag + "SKIP   ADX still warming up (needs ~29 prior days)");
					return;
				}
				if (adxPrev < AdxMin)
				{
					Print(tag + "SKIP   ADX " + adxPrev.ToString("F1") + " < " + AdxMin.ToString("F0") + " (not trending)");
					return;
				}
			}

			// ATR-target days need a valid prior-day ATR, else stand aside (matches Python)
			if (TargetMode == OrbTargetMode.Atr && (double.IsNaN(atrPrev) || atrPrev <= 0))
			{
				Print(tag + "SKIP   ATR still warming up (needs ~15 prior days)");
				return;
			}

			// vwap_slope bias
			bool up = true;
			if (Bias == OrbBiasMode.VwapSlope)
			{
				if (cumV <= 0 || !vwapStartCaptured || double.IsNaN(vwapStart))
				{
					Print(tag + "SKIP   VWAP-slope undetermined (no OR volume)");
					return;								// can't determine bias -> skip day
				}
				double vwapEnd = cumVP / cumV;			// running VWAP at OR close (= Python vws[-1])
				up = vwapEnd > vwapStart;
				dayAllowLong  = dayAllowLong  && up;
				dayAllowShort = dayAllowShort && !up;
			}

			if (!(dayAllowLong || dayAllowShort))
			{
				Print(tag + "SKIP   VWAP sloping " + (up ? "UP but shorts-only config" : "DOWN but longs-only config"));
				return;
			}

			dayTradeable = true;
			Print(tag + "TRADEABLE  " + (dayAllowLong ? "LONG " : "SHORT")
				+ "   ORwidth=" + widthPts.ToString("F1")
				+ "  ADXprev=" + adxPrev.ToString("F1")
				+ "  ATRprev=" + atrPrev.ToString("F1"));
		}

		// Target price for a side. RewardRisk = multiple of risk; Atr = k * prior-day ATR.
		private double ComputeTarget(double entry, double stop, bool isLong)
		{
			if (TargetMode == OrbTargetMode.Atr)
			{
				if (double.IsNaN(atrPrev) || atrPrev <= 0) return double.NaN;
				double dist = TargetAtrMult * atrPrev;
				return RoundTick(isLong ? entry + dist : entry - dist);
			}
			double risk = isLong ? (entry - stop) : (stop - entry);
			return RoundTick(isLong ? entry + RewardRiskRatio * risk
									: entry - RewardRiskRatio * risk);
		}

		// ---- Wilder ATR over daily H/L/C; returns the value through the LAST bar.
		// Identical to the Python _atr (seed = mean of the first `period` true ranges).
		private double WilderAtrLast(List<double> h, List<double> l, List<double> c, int period)
		{
			int n = h.Count;
			if (n < period + 1) return double.NaN;
			double[] tr = new double[n];
			for (int i = 1; i < n; i++)
				tr[i] = Math.Max(h[i] - l[i], Math.Max(Math.Abs(h[i] - c[i - 1]), Math.Abs(l[i] - c[i - 1])));
			double sum = 0.0;
			for (int i = 1; i <= period; i++) sum += tr[i];
			double atr = sum / period;					// atr at index `period`
			for (int i = period + 1; i < n; i++)
				atr = (atr * (period - 1) + tr[i]) / period;
			return atr;
		}

		// ---- Wilder ADX over daily H/L/C; returns the value through the LAST bar.
		// Identical to the Python _adx (needs >= 2*period+1 days to be valid).
		private double WilderAdxLast(List<double> h, List<double> l, List<double> c, int period)
		{
			int n = h.Count;
			if (n < 2 * period + 1) return double.NaN;
			double[] tr = new double[n], pdm = new double[n], mdm = new double[n];
			for (int i = 1; i < n; i++)
			{
				double up = h[i] - h[i - 1];
				double dn = l[i - 1] - l[i];
				pdm[i] = (up > dn && up > 0) ? up : 0.0;
				mdm[i] = (dn > up && dn > 0) ? dn : 0.0;
				tr[i]  = Math.Max(h[i] - l[i], Math.Max(Math.Abs(h[i] - c[i - 1]), Math.Abs(l[i] - c[i - 1])));
			}
			double[] atr = new double[n], sp = new double[n], sm = new double[n];
			double a = 0.0, p = 0.0, m = 0.0;
			for (int i = 1; i <= period; i++) { a += tr[i]; p += pdm[i]; m += mdm[i]; }
			atr[period] = a; sp[period] = p; sm[period] = m;
			for (int i = period + 1; i < n; i++)
			{
				atr[i] = atr[i - 1] - atr[i - 1] / period + tr[i];
				sp[i]  = sp[i - 1]  - sp[i - 1]  / period + pdm[i];
				sm[i]  = sm[i - 1]  - sm[i - 1]  / period + mdm[i];
			}
			double[] dx = new double[n];
			for (int i = period; i < n; i++)
			{
				double dip = atr[i] > 0 ? 100.0 * sp[i] / atr[i] : 0.0;
				double dim = atr[i] > 0 ? 100.0 * sm[i] / atr[i] : 0.0;
				double den = dip + dim;
				dx[i] = den > 0 ? 100.0 * Math.Abs(dip - dim) / den : 0.0;
			}
			int first = 2 * period;
			double s = 0.0;
			for (int i = period + 1; i <= first; i++) s += dx[i];
			double adx = s / period;					// adx at index `first`
			for (int i = first + 1; i < n; i++)
				adx = (adx * (period - 1) + dx[i]) / period;
			return adx;
		}

		// When one breakout fills, count it and kill the opposite pending order (OCO).
		protected override void OnExecutionUpdate(Execution execution, string executionId, double price, int quantity,
												  MarketPosition marketPosition, string orderId, DateTime time)
		{
			if (execution.Order == null) return;

			bool anyFill = execution.Order.OrderState == OrderState.Filled
						|| execution.Order.OrderState == OrderState.PartFilled;
			bool fullFill = execution.Order.OrderState == OrderState.Filled;
			if (!anyFill) return;

			if (execution.Order.Name == "ORlong" && execution.Order.OrderAction == OrderAction.Buy)
			{
				CancelIfWorking(shortEntry);
				if (fullFill) { tradesToday++; Print(currentDay.ToString("yyyy-MM-dd") + "  FILLED LONG  @ " + price); }
			}
			else if (execution.Order.Name == "ORshort" && execution.Order.OrderAction == OrderAction.SellShort)
			{
				CancelIfWorking(longEntry);
				if (fullFill) { tradesToday++; Print(currentDay.ToString("yyyy-MM-dd") + "  FILLED SHORT @ " + price); }
			}
		}

		private double RoundTick(double price)
		{
			return Instrument.MasterInstrument.RoundToTickSize(price);
		}

		private void CancelIfWorking(Order o)
		{
			if (o != null && (o.OrderState == OrderState.Working
						   || o.OrderState == OrderState.Accepted
						   || o.OrderState == OrderState.Submitted))
				CancelOrder(o);
		}

		#region Properties
		[NinjaScriptProperty]
		[Display(Name = "OR start time (HHmmss)", Description = "Time the opening range begins (chart time). 93000 = 09:30:00.", Order = 1, GroupName = "1. Opening Range")]
		public int OrStartTime { get; set; }

		[NinjaScriptProperty]
		[Range(1, int.MaxValue)]
		[Display(Name = "OR length (minutes)", Description = "Length of the opening range in minutes.", Order = 2, GroupName = "1. Opening Range")]
		public int OrMinutes { get; set; }

		[NinjaScriptProperty]
		[Display(Name = "Flatten time (HHmmss)", Description = "Force-flat any open position at/after this time. 155500 = 15:55:00.", Order = 3, GroupName = "1. Opening Range")]
		public int ExitTime { get; set; }

		[NinjaScriptProperty]
		[Range(0, 100000)]
		[Display(Name = "Max OR width (points)", Description = "Skip the day if the OR is wider than this (0 = off). Filters choppy / false-breakout days.", Order = 4, GroupName = "1. Opening Range")]
		public double MaxOrPoints { get; set; }

		[NinjaScriptProperty]
		[Display(Name = "Daily-agg start time (HHmmss)", Description = "Where each day's internal daily bar + session VWAP start accumulating. Set to your feed's daily start so ATR/ADX/VWAP match the backtest. 80000 = 08:00.", Order = 5, GroupName = "1. Opening Range")]
		public int DailyAggStartTime { get; set; }

		[NinjaScriptProperty]
		[Display(Name = "Daily-agg end time (HHmmss)", Description = "Where each day's internal daily bar + session VWAP stop accumulating. Keeps the overnight session out of the daily ATR/ADX. 170000 = 17:00.", Order = 6, GroupName = "1. Opening Range")]
		public int DailyAggEndTime { get; set; }

		[NinjaScriptProperty]
		[Range(0, int.MaxValue)]
		[Display(Name = "Breakout offset (ticks)", Description = "Extra ticks beyond the OR high/low for the entry; the stop sits the same distance beyond the opposite extreme.", Order = 1, GroupName = "2. Trade Management")]
		public int BreakoutOffsetTicks { get; set; }

		[NinjaScriptProperty]
		[Range(1, int.MaxValue)]
		[Display(Name = "Quantity (contracts)", Order = 2, GroupName = "2. Trade Management")]
		public int Quantity { get; set; }

		[NinjaScriptProperty]
		[Range(1, 20)]
		[Display(Name = "Max trades per day", Order = 3, GroupName = "2. Trade Management")]
		public int MaxTradesPerDay { get; set; }

		[NinjaScriptProperty]
		[Display(Name = "Allow long breakouts", Order = 4, GroupName = "2. Trade Management")]
		public bool EnableLong { get; set; }

		[NinjaScriptProperty]
		[Display(Name = "Allow short breakouts", Order = 5, GroupName = "2. Trade Management")]
		public bool EnableShort { get; set; }

		[NinjaScriptProperty]
		[Display(Name = "Directional bias", Description = "None = trade both sides. VwapSlope = take only the side the running session VWAP is sloping toward across the OR.", Order = 1, GroupName = "3. Filters")]
		public OrbBiasMode Bias { get; set; }

		[NinjaScriptProperty]
		[Display(Name = "Use ADX regime filter", Description = "Only trade when yesterday's daily ADX >= AdxMin (a trending regime).", Order = 2, GroupName = "3. Filters")]
		public bool UseAdxRegime { get; set; }

		[NinjaScriptProperty]
		[Range(1, 100)]
		[Display(Name = "ADX minimum", Description = "Minimum prior-day daily ADX to trade (regime filter).", Order = 3, GroupName = "3. Filters")]
		public double AdxMin { get; set; }

		[NinjaScriptProperty]
		[Range(2, 200)]
		[Display(Name = "ADX period", Order = 4, GroupName = "3. Filters")]
		public int AdxPeriod { get; set; }

		[NinjaScriptProperty]
		[Display(Name = "Target mode", Description = "Atr = target is TargetAtrMult * yesterday's daily ATR. RewardRisk = target is RewardRiskRatio * trade risk.", Order = 1, GroupName = "4. Target")]
		public OrbTargetMode TargetMode { get; set; }

		[NinjaScriptProperty]
		[Range(0.1, 100)]
		[Display(Name = "Target ATR multiple", Description = "Used when Target mode = Atr.", Order = 2, GroupName = "4. Target")]
		public double TargetAtrMult { get; set; }

		[NinjaScriptProperty]
		[Range(2, 200)]
		[Display(Name = "ATR period", Description = "Daily ATR period for the ATR target.", Order = 3, GroupName = "4. Target")]
		public int AtrPeriod { get; set; }

		[NinjaScriptProperty]
		[Range(0.1, 100)]
		[Display(Name = "Reward:Risk ratio", Description = "Used when Target mode = RewardRisk.", Order = 4, GroupName = "4. Target")]
		public double RewardRiskRatio { get; set; }
		#endregion
	}
}
