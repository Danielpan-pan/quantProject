from datetime import time, datetime, timedelta
import numpy as np
from collections import deque
from math import floor
from vnpy_ctastrategy import (
    CtaTemplate,
    BarGenerator,
    ArrayManager,
    TickData,
    BarData,
    TradeData,
    OrderData,
    StopOrder,
)
from vnpy.trader.constant import Interval


class SilverT(CtaTemplate):
    """
    T仓（日内/夜盘波段）交易策略 - 参数优化版
    - 21:30 锚点均线
    - 震荡市均值回归入场
    - 收盘前清仓
    - 名义资金占比式仓位控制（同向/反向差异化）
    """

    # ===== 优化后的参数 =====
    atr_length: int = 14  # 缩短ATR周期以更快响应市场变化
    use_atr_mode: bool = True  # 启用ATR自适应模式
    delta_entry: float = 1.2  # 入场触发（ATR倍数）1.2倍ATR
    tp_points: float = 3.0  # 止盈（ATR倍数）3倍ATR
    sl_points: float = 1.0  # 止损（ATR倍数）1倍ATR
    fixed_size: int = 15  # 提高期望下单手数上限
    cool_minutes: int = 15  # 缩短冷静时间至15分钟

    # 锚点均线
    anchor_time_str: str = "21:30"
    anchor_tolerance_min: int = 3  # 放宽锚点时间容差
    anchor_ma_days: int = 2  # 使用2日锚点均线平滑

    # 日内均价/VWAP
    use_vwap_anchor: bool = True  # 使用VWAP作为锚点
    intraday_acc_date = None  # 当前累计对应的自然日


    # 过滤参数优化
    days_for_filters: int = 2  # 缩短过滤周期至2天
    range_mult_enable_max: float = 2.0  # 放宽震荡判定阈值
    thrust_disable_mult: float = 3.0  # 放宽趋势过滤阈值

    # 交易时间规则
    no_entry_after: str = "14:50"  # 延后禁止开仓时间
    close_out_time: str = "14:55"  # 收盘前清仓时间
    daily_end: time = time(0, 0)  # 日线的收盘时间（回测数据设置 00:00）

    # 名义资金占比仓位控制
    account_equity: float = 1_000_000.0  # 账户名义资金（元）
    base_direction: int = 0  # 底仓方向：1=多，-1=空，0=无
    pct_neutral: float = 0.25  # 提高中性仓位比例至25%
    pct_same: float = 0.30  # 提高同向仓位比例至30%
    pct_opposite: float = 0.15  # 提高反向仓位比例至15%
    fallback_contract_size: float = 15.0  # 白银合约乘数

    parameters = [
        "atr_length",
        "use_atr_mode",
        "delta_entry",
        "tp_points",
        "sl_points",
        "fixed_size",
        "cool_minutes",
        "anchor_time_str",
        "anchor_tolerance_min",
        "anchor_ma_days",
        "days_for_filters",
        "range_mult_enable_max",
        "thrust_disable_mult",
        "no_entry_after",
        "close_out_time",
        "account_equity",
        "base_direction",
        "pct_neutral",
        "pct_same",
        "pct_opposite",
        "fallback_contract_size",
    ]

    # ===== 变量 =====
    atr_value: float = 0.0
    anchor_ma: float = 0.0
    in_cool: bool = False
    last_stop_time = None
    last_anchor_date = None

    anchor_prices: deque = deque(maxlen=anchor_ma_days)
    daily_high: dict = {}
    daily_low: dict = {}
    above_ma_days: deque = deque(maxlen=days_for_filters)

    variables = ["atr_value", "anchor_ma", "in_cool", "last_stop_time"]

    # ===== 初始化 =====
    def on_init(self):
        self.write_log("策略初始化")
        self.bg = BarGenerator(self.on_bar, 1, self.on_1min_bar)
        self.am = ArrayManager()
        self.bg_day = BarGenerator(
            self.on_bar,
            1,
            self.on_day_bar,
            interval=Interval.DAILY,
            daily_end=self.daily_end,
        )
        self.am_day = ArrayManager(size=14)
        self.load_bar(2000)

        # 获取合约乘数
        self.contract_size = self.fallback_contract_size
        try:
            contract = self.contract(self.vt_symbol)
            if contract and getattr(contract, "size", None):
                self.contract_size = float(contract.size)
                self.write_log(f"合约 {self.vt_symbol} 乘数: {self.contract_size}")
            else:
                self.write_log(
                    f"未找到 {self.vt_symbol} 合约信息，使用 fallback_contract_size={self.contract_size}"
                )
        except Exception as e:
            self.write_log(
                f"获取合约失败，使用 fallback_contract_size={self.contract_size}，err={e}"
            )

        # 解析时间字符串
        hh, mm = map(int, self.anchor_time_str.split(":"))
        self.anchor_time = time(hh, mm)
        nh, nm = map(int, self.no_entry_after.split(":"))
        self.no_entry_after_time = time(nh, nm)
        ch, cm = map(int, self.close_out_time.split(":"))
        self.close_out_time_obj = time(ch, cm)

        # 确保 deque 长度正确
        self.anchor_prices = (
            deque(self.anchor_prices, maxlen=self.anchor_ma_days)
            if isinstance(self.anchor_prices, deque)
            else deque(maxlen=self.anchor_ma_days)
        )
        self.above_ma_days = (
            deque(self.above_ma_days, maxlen=self.days_for_filters)
            if isinstance(self.above_ma_days, deque)
            else deque(maxlen=self.days_for_filters)
        )

    def on_start(self):
        self.write_log("策略启动")

    def on_stop(self):
        self.write_log("策略停止")

    # ===== 行情更新 =====
    def on_tick(self, tick: TickData):
        self.bg.update_tick(tick)
        self.bg_day.update_tick(tick)
        self.put_event()

    def on_bar(self, bar: BarData):
        self.bg.update_bar(bar)
        self.bg_day.update_bar(bar)
        self.put_event()

    def on_day_bar(self, bar: BarData):
        self.am_day.update_bar(bar)
        self.put_event()

    def on_1min_bar(self, bar: BarData):
        """主逻辑：基于 1 分钟 K 线"""

        # 维护日内均价/VWAP的累计数据
        self._update_intraday_accumulators(bar)

        if not self.trading:
            return

        self.cancel_all()
        self.am.update_bar(bar)
        if not self.am.inited:
            return

        # 0) ATR & 21:30 锚点均线维护
        self.atr_value = float(self.am.atr(self.atr_length))
        self._maybe_capture_anchor(bar)

        if len(self.anchor_prices) == 0:
            self.put_event()
            return

        self.anchor_ma = float(np.mean(self.anchor_prices))

        if self.in_cool and self.last_stop_time:
            if (bar.datetime - self.last_stop_time).total_seconds() >= self.cool_minutes * 60:
                self.in_cool = False

        # 1) 收盘前清仓
     #   if bar.datetime.time() >= self.close_out_time_obj:
     #       self._flatten_all(bar)
      #      self.put_event()
      #      return

        # 2) 日内禁开仓时间过滤
        if bar.datetime.time() >= self.no_entry_after_time:
            self.put_event()
            return

        # 3) 行情过滤
        rng_n, atr_n = self._recent_range_and_atr(n=self.days_for_filters)
        # 震荡市启用：Range <= k * ATR
        ranging_ok = (atr_n > 0) and (rng_n <= self.range_mult_enable_max * atr_n)
        # 主升浪禁用：Range >= 2*ATR
        thrust_disable = (atr_n > 0) and (rng_n >= self.thrust_disable_mult * atr_n)
        # 连续 N 天收在 anchor_ma 上方
        sustained_above = (len(self.above_ma_days) == self.days_for_filters) and all(
            self.above_ma_days
        )

        tradable = ranging_ok and (not thrust_disable) and (not sustained_above)
        if not tradable:
            self.put_event()
            return

        # 4) 信号
        delta = bar.close_price - self.anchor_ma

        # 使用ATR自适应模式计算阈值
        if self.use_atr_mode:
            entry_th = self.delta_entry * self.atr_value
            tp_val = self.tp_points * self.atr_value
            sl_val = self.sl_points * self.atr_value
        else:
            # 固定点数模式（保留但推荐使用ATR模式）
            entry_th = self.delta_entry
            tp_val = self.tp_points
            sl_val = self.sl_points

        # 5) 入场（名义占比+同向/反向规则限制数量）
        if self.pos == 0 and not self.in_cool:
            price = bar.close_price
            if delta <= -entry_th:
                max_lots = self._calc_allowed_lots(
                    direction=1, price=price, contract_size=self.contract_size
                )
                qty = max_lots
                if qty > 0:
                    self.buy(price, qty)
                    self.sell(price - sl_val, qty, stop=True)
                    self.sell(price + tp_val, qty, stop=True)

            elif delta >= entry_th:
                max_lots = self._calc_allowed_lots(
                    direction=-1, price=price, contract_size=self.contract_size
                )
                qty = max_lots
                if qty > 0:
                    self.short(price, qty)
                    self.cover(price + sl_val, qty, stop=True)
                    self.cover(price - tp_val, qty, stop=True)

        self.put_event()

    # ===== 订单 & 成交回调 =====
    def on_order(self, order: OrderData):
        pass

    def on_trade(self, trade: TradeData):
        # 简化：任一平仓成交都视为触发冷静期
        if trade.offset == "close":
            if (self.last_stop_time is None) or (
                (trade.datetime - self.last_stop_time).seconds >= self.cool_minutes * 60
            ):
                self.last_stop_time = trade.datetime
                self.in_cool = True

        self.put_event()

    def on_stop_order(self, stop_order: StopOrder):
        pass

    # ===== 辅助函数 =====
    def _flatten_all(self, bar: BarData):
        """收盘前清仓：无条件平掉全部持仓"""
        if self.pos > 0:
            self.sell(bar.close_price, abs(self.pos))
        elif self.pos < 0:
            self.cover(bar.close_price, abs(self.pos))

    def _calc_allowed_lots(
        self, direction: int, price: float, contract_size: float
    ) -> int:
        """
        根据名义资金约束计算最大可持仓手数。
        direction: 1=做多, -1=做空
        """
        # 按底仓方向决定允许占比
        if self.base_direction == 0:
            pct = self.pct_neutral
        elif self.base_direction == direction:
            pct = self.pct_same
        else:
            pct = self.pct_opposite

        # 最大名义可用额度（元）
        nominal_cap = max(0.0, self.account_equity * pct)

        # 单手名义价值（≈ price * 合约乘数）
        per_lot_notional = max(1e-9, price * contract_size)
        max_lots = floor(nominal_cap / per_lot_notional)

        # 添加调试日志
        self.write_log(
            f"仓位计算: 方向={direction}, 价格={price}, 合约大小={contract_size}, "
            f"账户资金={self.account_equity}, 比例={pct}, "
            f"名义额度={nominal_cap}, 单手价值={per_lot_notional}, "
            f"最大手数={max_lots}"
        )

        return int(max(0, max_lots))

    def _maybe_capture_anchor(self, bar: BarData) -> None:
        """
        每日捕捉一次 21:30 附近的锚点价（close），放入 anchor_prices。
        """
        d = bar.datetime.date()

        # 维护当日高低
        if d not in self.daily_high:
            self.daily_high[d] = bar.high_price
            self.daily_low[d] = bar.low_price
        else:
            self.daily_high[d] = max(self.daily_high[d], bar.high_price)
            self.daily_low[d] = min(self.daily_low[d], bar.low_price)

        # 当日已采集则跳过
        if self.last_anchor_date == d:
            return

        tol = timedelta(minutes=self.anchor_tolerance_min)
        anchor_dt = self._anchor_dt_same_tz(bar.datetime)
        if abs(bar.datetime - anchor_dt) <= tol:
            # 采集锚点价
            if self.use_vwap_anchor and self.day_vol_sum > 0:
                anchor_px = self.day_pv_sum / self.day_vol_sum
            else:
                # 简单日内均价：从当日第一根到当前（≈21:30）的均价
                denom = max(1, self.day_bar_count)
                anchor_px = self.day_price_sum / denom

            self.anchor_prices.append(anchor_px)
            self.last_anchor_date = d

            # 更新"当日是否站上前值 anchor_ma"的标志
            prev_ma = (
                float(np.mean(self.anchor_prices))
                if len(self.anchor_prices) > 0
                else bar.close_price
            )
            self.above_ma_days.append(bar.close_price > prev_ma)

            self._trim_old_days()

    def _recent_range_and_atr(self, n: int):
        # n 日 Range
        dates = sorted(self.daily_high.keys())[-n:]
        if not dates:
            return 0.0, 0.0

        hi = max(self.daily_high[d] for d in dates)
        lo = min(self.daily_low[d] for d in dates)
        rng = hi - lo

        # n 日 ATR
        if not self.am_day.inited:
            return rng, 0.0
        atr_val = self.am_day.atr(n)
        return rng, atr_val

    def _update_intraday_accumulators(self, bar: BarData) -> None:
        """
        维护日内均价/VWAP的累计数据。
        """
        d = bar.datetime.date()
        # 自然日切换则重置
        if self.intraday_acc_date != d:
            self.intraday_acc_date = d
            self.day_price_sum = 0.0
            self.day_bar_count = 0
            self.day_pv_sum = 0.0
            self.day_vol_sum = 0.0

        price = float(bar.close_price)
        self.day_price_sum += price
        self.day_bar_count += 1

        # 累计 VWAP
        try:
            vol = float(
                getattr(bar, "volume", 0.0)
            )  # vn.py BarData.volume 为该bar成交量
        except Exception:
            vol = 0.0

        if vol > 0:
            self.day_pv_sum += price * vol
            self.day_vol_sum += vol

    def _trim_old_days(self):
        """仅保留最近 days_for_filters+2 天的日高低缓存"""
        if len(self.daily_high) <= self.days_for_filters + 2:
            return
        sorted_days = sorted(self.daily_high.keys())
        while len(sorted_days) > self.days_for_filters + 2:
            d0 = sorted_days.pop(0)
            self.daily_high.pop(d0, None)
            self.daily_low.pop(d0, None)

    def _anchor_dt_same_tz(self, bar_dt: datetime) -> datetime:
        """构造与 bar_dt 同时区的当日 21:30，避免 naive/aware 错配"""
        hh, mm = self.anchor_time.hour, self.anchor_time.minute
        return bar_dt.replace(hour=hh, minute=mm, second=0, microsecond=0)