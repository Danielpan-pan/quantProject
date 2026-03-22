from typing import Optional
import numpy as np

from vnpy_ctastrategy import (
    CtaTemplate,
    BarGenerator,
    ArrayManager,
    TickData,
    BarData,
    OrderData,
    TradeData,
    StopOrder,
)


class RegimeSwitchDonchianBollStrategy(CtaTemplate):
    """
    Regime-Switching CTA:
      - Use ADX to detect trend vs range.
      - TREND regime: Donchian breakout with ATR buffer, initial stop and ATR trailing (Chandelier).
      - RANGE regime: Bollinger mean-reversion with RSI filter, exit at middle band or stop at band breach.
      - Risk: pricetick-aware limit orders, ATR initial stop, ATR trailing, cooldown between entries.
      - Kill-switch: N consecutive up bars -> close shorts; N consecutive down bars -> close longs.

    Works on 5-minute bars by default (can feed 5m directly or let BarGenerator aggregate).
    """

    author: str = "ChatGPT - RegimeSwitch"

    # ================= Parameters =================
    # Core timeframe and warmup
    am_size: int = 800
    lookback: int = 300  # min bars to ensure indicators are stable

    # Regime detection
    adx_len: int = 14
    adx_trend_th: float = 22.0  # ADX above -> trending; below -> ranging

    # TREND regime (Donchian breakout)
    donchian_n: int = 40  # breakout window (use previous N bars)
    atr_len: int = 22
    breakout_k_atr: float = 0.2  # extra ATR buffer on top of Donchian
    init_sl_atr: float = 2.0  # initial stop distance in ATR
    trail_atr_mult: float = 3.0  # Chandelier trailing

    # RANGE regime (Bollinger mean reversion)
    bb_len: int = 20
    bb_k: float = 2.0
    rsi_len: int = 7
    rsi_ob: float = 65.0  # overbought -> consider short near upper band
    rsi_os: float = 35.0  # oversold -> consider long near lower band

    # Orders/position
    tick_offset: int = 2  # price = last +/- tick_offset * pricetick
    fixed_size: int = 1
    max_pos: int = 1
    entry_cooldown: int = 3  # bars between entries

    # Streak emergency exit
    streak_n: int = 3

    # ================= Variables (UI) =================
    regime: str = "unknown"  # "trend" / "range"
    adx_val: float = 0.0
    atr_val: float = 0.0
    don_high: float = 0.0
    don_low: float = 0.0
    bb_mid: float = 0.0
    bb_up: float = 0.0
    bb_dn: float = 0.0
    rsi_val: float = 50.0

    up_streak: int = 0
    dn_streak: int = 0
    bars_since_entry: int = 9999
    high_since_entry: float = 0.0
    low_since_entry: float = 0.0
    entry_price: float = 0.0

    parameters = [
        "am_size",
        "lookback",
        "adx_len",
        "adx_trend_th",
        "donchian_n",
        "atr_len",
        "breakout_k_atr",
        "init_sl_atr",
        "trail_atr_mult",
        "bb_len",
        "bb_k",
        "rsi_len",
        "rsi_ob",
        "rsi_os",
        "tick_offset",
        "fixed_size",
        "max_pos",
        "entry_cooldown",
        "streak_n",
    ]

    variables = [
        "regime",
        "adx_val",
        "atr_val",
        "don_high",
        "don_low",
        "bb_mid",
        "bb_up",
        "bb_dn",
        "rsi_val",
        "up_streak",
        "dn_streak",
        "bars_since_entry",
        "high_since_entry",
        "low_since_entry",
        "entry_price",
    ]

    # ================= Lifecycle =================
    def on_init(self) -> None:
        self.write_log("Initializing RegimeSwitch strategy")
        self.bg = BarGenerator(self.on_bar, window=5, on_window_bar=self.on_5m_bar)
        self.am5 = ArrayManager(size=max(self.am_size, self.lookback + 100))
        self.load_bar(max(self.lookback + 100, 400))

    def on_start(self) -> None:
        self.write_log("Strategy started")

    def on_stop(self) -> None:
        self.write_log("Strategy stopped")

    # ================= Data plumbing =================
    def on_tick(self, tick: TickData) -> None:
        self.bg.update_tick(tick)

    def on_bar(self, bar: BarData) -> None:
        self.bg.update_bar(bar)

    def on_5m_bar(self, bar: BarData) -> None:
        self.cancel_all()

        am = self.am5
        am.update_bar(bar)
        if not am.inited:
            return

        close = bar.close_price

        # ---- Indicators ----
        self.atr_val = float(am.atr(self.atr_len))
        self.adx_val = float(self._adx(am, self.adx_len))
        self.regime = "trend" if self.adx_val >= self.adx_trend_th else "range"

        # Donchian (exclude current bar)
        if am.close.shape[0] > self.donchian_n:
            highs = am.high[-(self.donchian_n + 1) : -1]
            lows = am.low[-(self.donchian_n + 1) : -1]
            self.don_high = float(np.max(highs))
            self.don_low = float(np.min(lows))

        # Bollinger
        self.bb_mid, self.bb_up, self.bb_dn = self._boll(am, self.bb_len, self.bb_k)

        # RSI
        self.rsi_val = float(self._rsi(am, self.rsi_len))

        # ---- Exits first: streak emergency ----
        self._update_streaks(am)
        if self.up_streak >= self.streak_n and self.pos < 0:
            self._cover_all(close)
        if self.dn_streak >= self.streak_n and self.pos > 0:
            self._sell_all(close)

        # ---- Regime logics ----
        if self.regime == "trend":
            self._trend_logic(close)
        else:
            self._range_logic(close)

        # ---- Trailing stops after entries/exits ----
        self._place_trailing_stops()

        # ---- Book-keeping ----
        self._update_extremes_and_cooldown(bar)

        self.put_event()

    # ================= Trend regime (Donchian breakout) =================
    def _trend_logic(self, close: float) -> None:
        if self.atr_val <= 0 or self.don_high <= 0 or self.don_low <= 0:
            return

        buf = self.breakout_k_atr * self.atr_val
        up_break = self.don_high + buf
        dn_break = self.don_low - buf

        # Exit on opposite Donchian touch (soft take profit)
        if self.pos > 0 and close <= self.don_mid():
            self._sell_all(close)
        elif self.pos < 0 and close >= self.don_mid():
            self._cover_all(close)

        # Entries with cooldown
        if self.bars_since_entry >= self.entry_cooldown:
            if close > up_break and self.pos < self.max_pos:
                self._buy_with_init_sl(close)
            elif close < dn_break and -self.pos < self.max_pos:
                self._short_with_init_sl(close)

    def don_mid(self) -> float:
        return (
            (self.don_high + self.don_low) / 2.0
            if (self.don_high > 0 and self.don_low > 0)
            else 0.0
        )

    # ================= Range regime (Bollinger MR) =================
    def _range_logic(self, close: float) -> None:
        if self.bb_up == 0 or self.bb_dn == 0:
            return

        # Mean reversion entries near bands plus RSI filter
        near_upper = close >= self.bb_up and self.rsi_val >= self.rsi_ob
        near_lower = close <= self.bb_dn and self.rsi_val <= self.rsi_os

        # Exit rules for MR: take profit at middle band; stop if breach of opposite band
        if self.pos > 0:
            if close >= self.bb_mid:
                self._sell_all(close)
            elif close < self.bb_dn - 0.2 * self.atr_val:
                # stop if further selloff below band
                self._sell_all(close)
        elif self.pos < 0:
            if close <= self.bb_mid:
                self._cover_all(close)
            elif close > self.bb_up + 0.2 * self.atr_val:
                self._cover_all(close)

        if self.bars_since_entry >= self.entry_cooldown:
            if near_lower and self.pos < self.max_pos:
                self._buy_with_init_sl(close)
            elif near_upper and -self.pos < self.max_pos:
                self._short_with_init_sl(close)

    # ================= Orders & Risk =================
    def _buy_with_init_sl(self, last: float) -> None:
        px = self._limit_buy(last)
        self.buy(px, self.fixed_size)
        # Initial ATR stop
        if self.atr_val > 0:
            sl = self._round_to_tick(px - self.init_sl_atr * self.atr_val)
            self.sell(sl, self.fixed_size, stop=True)
        self._reset_after_entry(px)

    def _short_with_init_sl(self, last: float) -> None:
        px = self._limit_sell(last)
        self.short(px, self.fixed_size)
        if self.atr_val > 0:
            sl = self._round_to_tick(px + self.init_sl_atr * self.atr_val)
            self.cover(sl, self.fixed_size, stop=True)
        self._reset_after_entry(px)

    def _place_trailing_stops(self) -> None:
        """Chandelier-style ATR trailing."""
        if self.atr_val <= 0:
            return
        if self.pos > 0:
            trail = self._round_to_tick(
                self.high_since_entry - self.trail_atr_mult * self.atr_val
            )
            self.sell(trail, abs(self.pos), stop=True)
        elif self.pos < 0:
            trail = self._round_to_tick(
                self.low_since_entry + self.trail_atr_mult * self.atr_val
            )
            self.cover(trail, abs(self.pos), stop=True)

    def _sell_all(self, last: float) -> None:
        if self.pos > 0:
            self.sell(self._limit_sell(last), abs(self.pos))

    def _cover_all(self, last: float) -> None:
        if self.pos < 0:
            self.cover(self._limit_buy(last), abs(self.pos))

    def _limit_buy(self, last: float) -> float:
        tick = getattr(self.contract, "pricetick", 1.0)
        return self._round_to_tick(last + self.tick_offset * tick)

    def _limit_sell(self, last: float) -> float:
        tick = getattr(self.contract, "pricetick", 1.0)
        return self._round_to_tick(last - self.tick_offset * tick)

    def _reset_after_entry(self, price: float) -> None:
        self.bars_since_entry = 0
        self.entry_price = price
        self.high_since_entry = price
        self.low_since_entry = price

    # ================= Indicators =================
    def _boll(self, am: ArrayManager, length: int, k: float):
        if am.close.shape[0] < length:
            return 0.0, 0.0, 0.0
        closes = am.close[-length:]
        mid = float(np.mean(closes))
        std = float(np.std(closes, ddof=0))
        up = mid + k * std
        dn = mid - k * std
        self.bb_mid = mid
        return mid, up, dn

    def _rsi(self, am: ArrayManager, length: int) -> float:
        if am.close.shape[0] <= length:
            return 50.0
        return float(am.rsi(length))

    def _adx(self, am: ArrayManager, length: int) -> float:
        """
        Wilder's ADX on high/low/close.
        """
        if am.close.shape[0] <= length + 1:
            return 0.0
        high = am.high[-(length * 3 + 3) :].astype(float)
        low = am.low[-(length * 3 + 3) :].astype(float)
        close = am.close[-(length * 3 + 3) :].astype(float)
        n = len(close)
        if n < length + 2:
            return 0.0

        # True Range
        tr = np.zeros(n)
        tr[1:] = np.maximum.reduce(
            [
                high[1:] - low[1:],
                np.abs(high[1:] - close[:-1]),
                np.abs(low[1:] - close[:-1]),
            ]
        )
        # +DM / -DM
        up_move = high[1:] - high[:-1]
        dn_move = low[:-1] - low[1:]
        plus_dm = np.where((up_move > dn_move) & (up_move > 0), up_move, 0.0)
        minus_dm = np.where((dn_move > up_move) & (dn_move > 0), dn_move, 0.0)

        # Wilder's smoothing
        def wilder_smooth(arr, period):
            out = np.zeros_like(arr)
            out[period] = np.sum(arr[1 : period + 1])
            for i in range(period + 1, len(arr)):
                out[i] = out[i - 1] - (out[i - 1] / period) + arr[i]
            return out

        tr_s = wilder_smooth(tr, length)
        plus_dm_s = wilder_smooth(np.r_[0.0, plus_dm], length)
        minus_dm_s = wilder_smooth(np.r_[0.0, minus_dm], length)

        plus_di = 100.0 * (plus_dm_s / np.maximum(tr_s, 1e-12))
        minus_di = 100.0 * (minus_dm_s / np.maximum(tr_s, 1e-12))
        dx = 100.0 * np.abs(plus_di - minus_di) / np.maximum(plus_di + minus_di, 1e-12)

        # ADX: Wilder's smoothing of DX
        adx = np.zeros_like(dx)
        start = length * 2
        if len(dx) <= start:
            return 0.0
        adx[start] = np.mean(dx[length + 1 : start + 1])
        for i in range(start + 1, len(dx)):
            adx[i] = (adx[i - 1] * (length - 1) + dx[i]) / length

        return float(adx[-1])

    # ================= Utilities & bookkeeping =================
    def _update_streaks(self, am: ArrayManager) -> None:
        if am.close.shape[0] < 2:
            return
        c0, c1 = am.close[-1], am.close[-2]
        if c0 > c1:
            self.up_streak += 1
            self.dn_streak = 0
        elif c0 < c1:
            self.dn_streak += 1
            self.up_streak = 0
        else:
            self.up_streak = 0
            self.dn_streak = 0

    def _update_extremes_and_cooldown(self, bar: BarData) -> None:
        self.bars_since_entry += 1
        if self.pos > 0:
            self.high_since_entry = max(self.high_since_entry, bar.high_price)
            self.low_since_entry = min(self.low_since_entry, bar.low_price)
        elif self.pos < 0:
            self.low_since_entry = min(self.low_since_entry, bar.low_price)
            self.high_since_entry = max(self.high_since_entry, bar.high_price)

    def _round_to_tick(self, price: float) -> float:
        tick = getattr(self.contract, "pricetick", 1.0)
        if tick <= 0:
            return price
        return round(price / tick) * tick

    # ================= Events =================
    def on_order(self, order: OrderData) -> None:
        pass

    def on_trade(self, trade: TradeData) -> None:
        self.put_event()

    def on_stop_order(self, stop_order: StopOrder) -> None:
        pass
