from datetime import time, date, datetime, timedelta
from typing import Dict, List, Optional, Tuple
import collections
import numpy as np
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
from utils.logger import DummyRunLogger


class SilverT(CtaTemplate):
    """
    T仓（日内/夜盘波段）交易策略
    - 21:30 锚点均线
    - 震荡市均值回归入场
    - 收盘前清仓
    - 名义资金占比式仓位控制（同向/反向差异化）
    """

    logger = DummyRunLogger()

    # ===== 参数 =====

    # 21:00-21:30锚点价格窗口
    # 添加新变量 2025/10/24 是否波动超过100点
    break_100_occurred = False

    # 新增变量
    anchor_window_prices: List[float] = []  # 存储21:00-21:30之间的价格
    anchor_window_start = time(21, 0)  # 窗口开始时间
    anchor_window_end = time(21, 30)  # 窗口结束时间

    # ATR & entry/exit
    atr_length: int = 14
    use_atr_mode: bool = True  # 是否启用 ATR 自适应版（默认启用）

    delta_entry_atr: float = 1.2  # 入场触发 Δ（ATR倍数）
    # 风控层：ATR比例止盈止损（统一使用ATR比例）
    tp_multiplier: float = 2.0  # 止盈倍数 C1（ATR倍数）
    sl_multiplier: float = 0.8  # 止损倍数 C2（ATR倍数）
    # 目标盈亏比 R = TP/SL = C1/C2，应在[2.0, 2.5]之间
    # 当前 R = 2.0/0.8 = 2.5，符合要求

    # 浮盈追踪止盈参数
    trail_multiplier_min: float = 1.2  # 追踪止盈最小倍数
    trail_multiplier_max: float = 1.6  # 追踪止盈最大倍数

    # 事件过滤参数
    event_block_minutes: int = 15  # 重大数据发布前后禁开仓时间（分钟）
    # 重大数据发布时间列表（示例，可根据实际情况配置）
    event_times: List[Tuple[time, str]] = [
        # (time(20, 30), "美国非农数据"),  # 示例：20:30发布
        # (time(22, 0), "美联储利率决议"),  # 示例：22:00发布
    ]

    # 波动过滤参数
    volatility_threshold_mult: float = 0.5  # 一分钟波动幅度阈值（ATR倍数）
    volatility_penalty_min: float = 0.10  # 波动过大时提高入场阈值的最小比例
    volatility_penalty_max: float = 0.20  # 波动过大时提高入场阈值的最大比例

    # 旧参数（保留兼容性，但不再使用）
    tp_points_atr: float = 3.0  # 已废弃，使用tp_multiplier
    sl_points_atr: float = 1.0  # 已废弃，使用sl_multiplier
    delta_entry: float = 50.0  # 入场触发 Δ（点/元，仅在非ATR模式下使用）
    tp_points: float = 90.0  # 已废弃，使用tp_multiplier
    sl_points: float = 30.0  # 已废弃，使用sl_multiplier

    fixed_size: int = 10  # 期望下单手数上限（仍受名义占比约束）
    cool_minutes: int = 30  # 止损后冷静时间（分钟）
    close_out: bool = True  # 启用收盘前清仓
    use_tick_trading: bool = True  # 实盘场景下启用 Tick 级联动
    tick_timeout_seconds: int = 90  # Tick 中断多少秒后退回 Bar 执行

    # 日内均价/VWAP
    use_vwap_anchor: bool = True  # 启用 VWAP 作为锚点价
    day_price_sum: float = 0.0  # ∑ close（或你想用的价格）
    day_bar_count: int = 0  # 计数
    day_pv_sum: float = 0.0  # ∑(price * volume)（VWAP 用）
    day_vol_sum: float = 0.0  # ∑ volume（VWAP 用）
    intraday_acc_date: Optional[date] = None  # 当前累计对应的自然日

    # 过滤
    days_for_filters: int = 3
    range_mult_enable_max: float = 1.5
    thrust_disable_mult: float = 2.0

    # 交易时间规则
    anchor_time_str: str = "21:30"
    no_entry_after_str: str = "14:00"

    daily_end: time = time(14, 59)  # 日线的收盘时间（用于计算日线）
    # daily_end: time = time(0, 0)  # 日线的收盘时间（回测数据设置 00:00）
    close_out_minutes_before_end: int = 30  # 收盘前多少分钟清仓

    # 锚点均线
    anchor_tolerance_min: int = 3
    anchor_ma_days: int = 1

    # 名义资金占比仓位控制
    account_equity: float = 2_000_000.0  # 账户名义资金（元）
    base_direction: int = 0  # 底仓方向：1=多，-1=空，0=无
    pct_neutral: float = 0.25  # 与底仓无关时：≤25%
    pct_same: float = 0.30  # 与底仓同向：≤30%
    pct_opposite: float = 0.15  # 与底仓反向：≤15%
    fallback_contract_size: float = 15.0  # 白银合约乘数（若无法获取合约信息则使用该值）

    parameters = [
        "atr_length",
        "use_atr_mode",
        "delta_entry",
        "tp_points",
        "sl_points",
        "tp_multiplier",
        "sl_multiplier",
        "trail_multiplier_min",
        "trail_multiplier_max",
        "event_block_minutes",
        "volatility_threshold_mult",
        "volatility_penalty_min",
        "volatility_penalty_max",
        "fixed_size",
        "cool_minutes",
        "anchor_time_str",
        "no_entry_after_str",
        "anchor_tolerance_min",
        "anchor_ma_days",
        "days_for_filters",
        "range_mult_enable_max",
        "thrust_disable_mult",
        "account_equity",
        "base_direction",
        "pct_neutral",
        "pct_same",
        "pct_opposite",
        "use_tick_trading",
        "tick_timeout_seconds",
        "fallback_contract_size",
    ]

    # ===== 变量 =====
    atr_value: float = 0.0
    anchor_ma: float = 0.0
    in_cool: bool = False
    last_stop_time: Optional[datetime] = None
    last_anchor_date: Optional[date] = None
    last_tick_dt: Optional[datetime] = None

    anchor_prices: collections.deque[float] = collections.deque(maxlen=anchor_ma_days)
    daily_high: Dict[date, float] = {}
    daily_low: Dict[date, float] = {}
    above_ma_days: collections.deque[bool] = collections.deque(maxlen=days_for_filters)

    entry_price_long = 0.0
    tp_price_long = 0.0
    sl_price_long = 0.0
    trail_price_long = 0.0  # 追踪止盈触发价（多头）
    highest_price_long = 0.0  # 持仓期间最高价（用于追踪止盈）

    entry_price_short = 0.0
    tp_price_short = 0.0
    sl_price_short = 0.0
    trail_price_short = 0.0  # 追踪止盈触发价（空头）
    lowest_price_short = 0.0  # 持仓期间最低价（用于追踪止盈）

    # 事件过滤相关
    event_block: bool = False  # 事件阻塞信号（True表示禁开新仓）
    last_bar_high: float = 0.0  # 上一根K线最高价（用于计算一分钟波动）
    last_bar_low: float = 0.0  # 上一根K线最低价（用于计算一分钟波动）
    volatility_penalty: float = 0.0  # 当前波动惩罚比例（0-0.2）

    variables = [
        "atr_value",
        "anchor_ma",
        "in_cool",
        "last_stop_time",
        "last_anchor_date",
        "last_tick_dt",
        "anchor_prices",
        "daily_high",
        "daily_low",
        "above_ma_days",
        "event_block",
        "volatility_penalty",
    ]

    # ===== 初始化 =====
    def on_init(self) -> None:
        self.logger.info("策略初始化")
        self.bg = BarGenerator(self.on_bar, 1, self.on_1min_bar)
        self.bg_day = BarGenerator(
            self.on_bar,
            1,
            self.on_day_bar,
            interval=Interval.DAILY,
            daily_end=self.daily_end,
        )

        self.am = ArrayManager(size=840)
        self.am_day = ArrayManager(size=14)

        # self.load_bar(2000)

        # 获取合约乘数
        try:
            contract = self.cta_engine.main_engine.get_contract(self.vt_symbol)
            if contract:
                self.contract_size = float(contract.size)
            self.logger.info(f"合约乘数: {self.contract_size}")
        except Exception as e:
            self.logger.info(f"获取合约失败, err={e}")
            self.contract_size = self.fallback_contract_size

        # 从 CTP 获取账户资金
        try:
            account = self.cta_engine.main_engine.get_account(
                self.cta_engine.main_engine.get_all_accounts()[0].vt_accountid
            )
            if account:
                self.account_equity = float(account.available)
                self.logger.info(f"账户总权益: {self.account_equity}")
            else:
                self.logger.info(f"未找到账户信息")
        except Exception as e:
            self.logger.info(f"获取账户信息失败: {e}")

        # 计算收盘前清仓时间
        dt = datetime.combine(datetime.today(), self.daily_end)
        self.close_out_time = (
            dt - timedelta(minutes=self.close_out_minutes_before_end)
        ).time()

        # 确保 deque 长度正确（防止策略重启时参数变更导致的长度不符）
        self.anchor_prices = (
            collections.deque(self.anchor_prices, maxlen=self.anchor_ma_days)
            if isinstance(self.anchor_prices, collections.deque)
            else collections.deque(maxlen=self.anchor_ma_days)
        )
        self.logger.info(f"初始化九点半的均线队列为：{self.anchor_prices}")

        self.above_ma_days = (
            collections.deque(self.above_ma_days, maxlen=self.days_for_filters)
            if isinstance(self.above_ma_days, collections.deque)
            else collections.deque(maxlen=self.days_for_filters)
        )

        hh, mm = map(int, self.anchor_time_str.split(":"))
        self.anchor_time = time(hh, mm)

        hh2, mm2 = map(int, self.no_entry_after_str.split(":"))
        self.no_entry_after = time(hh2, mm2)

    def on_start(self) -> None:
        self.logger.info("策略启动")

    def on_stop(self) -> None:
        self.logger.info("策略停止")

    # ===== 行情更新 =====
    def on_tick(self, tick: TickData) -> None:
        self.write_log(f"on_tick: {tick.datetime} - {tick.last_price}")
        self.bg.update_tick(tick)
        self.bg_day.update_tick(tick)
        self.last_tick_dt = tick.datetime

        if self.trading and self.use_tick_trading:
            price = self._get_tick_price(tick)
            if price > 0:
                self._evaluate_signal(
                    price=price,
                    dt=tick.datetime,
                    source="tick",
                    allow_entry=True,
                )

        self.put_event()

    def on_bar(self, bar: BarData) -> None:
        self.bg.update_bar(bar)
        self.bg_day.update_bar(bar)
        self.put_event()

    def on_day_bar(self, bar: BarData) -> None:
        self.am_day.update_bar(bar)
        self.put_event()

    def on_1min_bar(self, bar: BarData) -> None:
        """主逻辑：基于 1 分钟 K 线"""

        # 维护日内均价/VWAP的累计数据
        self._update_intraday_accumulators(bar)

        self.am.update_bar(bar)
        if self.am.inited:
            self.atr_value = float(self.am.atr(self.atr_length))

        # 锚点均线维护
        self._maybe_capture_anchor(bar)

        # 检查事件阻塞
        self._update_event_block(bar.datetime)

        # 计算一分钟波动并更新波动惩罚
        self._update_volatility_penalty(bar)

        # 更新追踪止盈（如果有持仓）
        if self.pos != 0:
            self._update_trailing_stop(bar)

        allow_entry = self._should_use_bar_entry(bar.datetime)
        self._evaluate_signal(
            price=bar.close_price,
            dt=bar.datetime,
            source="bar",
            allow_entry=allow_entry,
        )

        # 更新上一根K线数据
        self.last_bar_high = bar.high_price
        self.last_bar_low = bar.low_price

        self._write_bar_1m_to_db(bar)
        self.put_event()

    # ===== 订单 & 成交回调 =====
    def on_order(self, order: OrderData) -> None:
        pass

    def on_trade(self, trade: TradeData) -> None:
        # 任一平仓成交都视为触发冷静期（可改为仅SL触发）
        if trade.offset == "close":
            if (self.last_stop_time is None) or (
                (trade.datetime - self.last_stop_time).seconds >= self.cool_minutes * 60
            ):
                self.last_stop_time = trade.datetime
                self.in_cool = True

        # 开仓时初始化追踪止盈相关变量
        if trade.offset == "open":
            if trade.direction == "long":
                self.entry_price_long = trade.price
                self.highest_price_long = trade.price
            elif trade.direction == "short":
                self.entry_price_short = trade.price
                self.lowest_price_short = trade.price

        # 清理目标价
        if self.pos == 0:
            self.cancel_all()
            self.entry_price_long = self.tp_price_long = self.sl_price_long = 0.0
            self.trail_price_long = self.highest_price_long = 0.0
            self.entry_price_short = self.tp_price_short = self.sl_price_short = 0.0
            self.trail_price_short = self.lowest_price_short = 0.0

        # 更新账户权益
        try:
            account = self.get_account()
            if account and getattr(account, "total_equity", None):
                self.account_equity = float(account.total_equity)
        except Exception as e:
            self.write_log(
                f"获取账户信息失败，使用预设 account_equity={self.account_equity}，err={e}"
            )

        self.put_event()

    def on_stop_order(self, stop_order: StopOrder) -> None:
        # placeholder for stop order handling
        pass

    # ===== 辅助函数 =====
    def _flatten_all(self, price: float) -> None:
        """收盘前清仓：无条件平掉全部持仓"""
        self.cancel_all()
        if self.pos > 0:
            self.sell(price, abs(self.pos))
        elif self.pos < 0:
            self.cover(price, abs(self.pos))

    def _evaluate_signal(
        self, price: float, dt: datetime, source: str, allow_entry: bool
    ) -> None:
        """统一的信号评估流程，Tick/Bar 共用。"""
        if price <= 0:
            return

        if not self.trading:
            return

        if not self.am.inited:
            return

        if len(self.anchor_prices) == 0:
            return

        self.anchor_ma = float(np.mean(self.anchor_prices))
        current_time = dt.strftime("%Y-%m-%d %H:%M:%S")

        if (source == "bar") and (not self.break_100_occurred):
            diff = abs(price - self.anchor_ma)
            if diff >= 100:
                self.break_100_occurred = True
                self.write_log(
                    f"{current_time} - 价格突破均线100点({diff:.2f})，在下一次获取锚点价格之前不再交易"
                )

        if self.break_100_occurred:
            return

        if self.in_cool and self.last_stop_time:
            if (dt - self.last_stop_time).total_seconds() >= self.cool_minutes * 60:
                self.in_cool = False

        if self.close_out and dt.time() >= self.close_out_time:
            if self.pos != 0:
                self.write_log(f"{current_time} - 收盘前清仓，使用价格 {price}")
            self._flatten_all(price)
            return

        if (
            dt.time() >= self.no_entry_after and dt.time() < self.daily_end
        ):  # 日内禁开仓时间
            return

        if self.anchor_window_start <= dt.time() <= self.anchor_window_end:
            if source == "bar":
                self.write_log(f"{current_time} - 21:00-21:30期间禁止开仓")
            return

        rng_n, atr_n = self._recent_range_and_atr(n=self.days_for_filters)
        ranging_ok = (atr_n > 0) and (rng_n <= self.range_mult_enable_max * atr_n)
        thrust_disable = (atr_n > 0) and (rng_n >= self.thrust_disable_mult * atr_n)
        sustained_above = (len(self.above_ma_days) == self.days_for_filters) and all(
            self.above_ma_days
        )

        if source == "bar":
            self.write_log(
                f"{current_time} - 最近{self.days_for_filters}日 Range={rng_n:.2f}, "
                f"ATR={atr_n:.2f}, 震荡市允许={ranging_ok}, "
                f"主升浪禁用={thrust_disable}, "
                f"连续{self.days_for_filters}日收在均线上方={sustained_above}"
            )

        tradable = ranging_ok and (not thrust_disable) and (not sustained_above)
        if not tradable:
            return

        delta = price - self.anchor_ma

        # 风控层：统一使用ATR比例定义止盈止损
        if self.use_atr_mode:
            # 基础入场阈值
            base_entry_th = self.delta_entry_atr * self.atr_value
            # 应用波动惩罚（如果波动过大）
            entry_th = base_entry_th * (1.0 + self.volatility_penalty)

            # 使用新的ATR比例止盈止损（C1=2.0, C2=0.8）
            tp_val = self.tp_multiplier * self.atr_value
            sl_val = self.sl_multiplier * self.atr_value
        else:
            entry_th = self.delta_entry
            tp_val = self.tp_points
            sl_val = self.sl_points

        # 检查事件阻塞：如果event_block为True，禁止开新仓
        if self.event_block and allow_entry and self.pos == 0:
            if source == "bar":
                self.write_log(
                    f"{current_time} - 事件阻塞：重大数据发布前后±{self.event_block_minutes}分钟，禁止开新仓"
                )
            return

        if allow_entry and self.pos == 0 and not self.in_cool:
            if delta <= -entry_th:
                max_lots = self._calc_allowed_lots(1, price, self.contract_size)
                qty = max(0, min(self.fixed_size, max_lots))
                if qty > 0:
                    self.cancel_all()
                    self.entry_price_long = price
                    self.sl_price_long = price - sl_val
                    self.tp_price_long = price + tp_val
                    # 初始化追踪止盈相关变量
                    self.highest_price_long = price
                    self.trail_price_long = 0.0

                    self.buy(price, qty)
                    self.sell(self.sl_price_long, qty, stop=True)
                    self.sell(self.tp_price_long, qty)

                    # 计算盈亏比
                    r_ratio = tp_val / sl_val if sl_val > 0 else 0.0
                    self.write_log(
                        f"当前维护21.30均线为：{self.anchor_ma}，"
                        f"入场偏移量：{delta:.2f}，"
                        f"入场指定金额：{entry_th:.2f}，"
                        f"ATR={self.atr_value:.2f}，"
                        f"盈亏比R={r_ratio:.2f}，"
                        f"{current_time} - 多头入场: price={price:.2f}, qty={qty}, "
                        f"sl={self.sl_price_long:.2f}, tp={self.tp_price_long:.2f}"
                    )

            elif delta >= entry_th:
                max_lots = self._calc_allowed_lots(-1, price, self.contract_size)
                qty = max(0, min(self.fixed_size, max_lots))
                if qty > 0:
                    self.cancel_all()
                    self.entry_price_short = price
                    self.sl_price_short = price + sl_val
                    self.tp_price_short = price - tp_val
                    # 初始化追踪止盈相关变量
                    self.lowest_price_short = price
                    self.trail_price_short = 0.0

                    self.short(price, qty)
                    self.cover(self.sl_price_short, qty, stop=True)
                    self.cover(self.tp_price_short, qty)

                    # 计算盈亏比
                    r_ratio = tp_val / sl_val if sl_val > 0 else 0.0
                    self.write_log(
                        f"入场偏移量：{delta:.2f}，"
                        f"入场指定金额：{entry_th:.2f}，"
                        f"ATR={self.atr_value:.2f}，"
                        f"盈亏比R={r_ratio:.2f}，"
                        f"{current_time} - 空头入场: price={price:.2f}, qty={qty}, "
                        f"sl={self.sl_price_short:.2f}, tp={self.tp_price_short:.2f}"
                    )

    def _get_tick_price(self, tick: TickData) -> float:
        """从 Tick 中提取用于判断的价格。"""
        price = float(getattr(tick, "last_price", 0.0) or 0.0)
        if price <= 0:
            ask = float(getattr(tick, "ask_price_1", 0.0) or 0.0)
            bid = float(getattr(tick, "bid_price_1", 0.0) or 0.0)
            price = ask or bid
        return price

    def _should_use_bar_entry(self, dt: datetime) -> bool:
        """
        Tick 执行开启但长时间无 Tick 时，回退到 Bar 入场。
        """
        if not self.use_tick_trading:
            return True

        if not self.last_tick_dt:
            return True

        return (dt - self.last_tick_dt).total_seconds() > self.tick_timeout_seconds

    def _write_bar_1m_to_db(self, bar: BarData) -> None:
        """
        将 1m K 线写入数据库的 bar_1m 表；需要 RunLogger 已用 db_dsn 初始化。
        """
        rl = self.logger
        if not rl or not getattr(rl, "engine", None):
            return  # 未启用数据库写入则跳过

        try:
            # strategy_id 直接用策略名；symbol 用 vt_symbol
            strategy_id = getattr(self, "strategy_name", self.__class__.__name__)
            account_id = getattr(self, "account_id", "default")
            symbol = (
                getattr(self, "vt_symbol", None)
                or getattr(bar, "vt_symbol", None)
                or "UNKNOWN"
            )
            csize = getattr(self, "contract_size", self.fallback_contract_size)

            # 直接复用 logger 的便捷方法（内含 UPSERT）
            rl.upsert_bar_1m_from_bar(
                bar_obj=bar,
                strategy_id=strategy_id,
                account_id=account_id,
                contract_size=csize,
                symbol=symbol,
            )
        except Exception as e:
            # 不让异常影响交易主逻辑
            self.write_log(f"写入 bar_1m 失败: {e}")

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
        per_lot_notional = max(1e-9, price * max(1.0, contract_size))
        max_lots = floor(nominal_cap / per_lot_notional)

        # 添加调试日志
        # self.write_log(
        #     f"仓位计算: 方向={direction}, 价格={price}, 合约大小={contract_size}, "
        #     f"账户资金={self.account_equity}, 比例={pct}, "
        #     f"名义额度={nominal_cap}, 单手价值={per_lot_notional}, "
        #     f"最大手数={max_lots}",
        # )

        return int(max(0, max_lots))

    def _maybe_capture_anchor(self, bar: BarData) -> None:
        """
        每日捕捉一次 21:30 附近的锚点价（close），放入 anchor_prices。
        """
        global anchor_px
        d = bar.datetime.date()
        bar_time = bar.datetime.time()

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

        if self.anchor_window_start <= bar_time <= self.anchor_window_end:
            # 使用收盘价，也可以考虑使用VWAP或其他价格
            self.anchor_window_prices.append(bar.close_price)

        # 窗口结束时计算平均价格
        if bar_time >= self.anchor_window_end:
            if self.anchor_window_prices:
                # 计算平均价格
                anchor_px = sum(self.anchor_window_prices) / len(
                    self.anchor_window_prices
                )
                self.anchor_prices.append(anchor_px)
                self.last_anchor_date = d
                # 获取新的锚点价格后重置突破限制（但只重置当天发生的突破）
                if self.break_100_occurred:
                    self.break_100_occurred = False
                    self.write_log(
                        f"{bar.datetime.strftime('%Y-%m-%d %H:%M:%S')} - 已获取新的锚点价格，解除突破限制"
                    )

                # 记录日志
                self.write_log(
                    f"{bar.datetime.strftime('%Y-%m-%d %H:%M:%S')} -"
                    f"此时记录的均线计算数据为：{self.anchor_window_prices}"
                    f"计算21:00-21:30均线: {anchor_px:.2f}, 使用{len(self.anchor_window_prices)}个价格点"
                )
            # 更新“当日是否站上前值 anchor_ma”的标志
            prev_ma = (
                float(np.mean(self.anchor_prices))
                if len(self.anchor_prices) > 0
                else bar.close_price
            )
            self.above_ma_days.append(bar.close_price > prev_ma)
            self._trim_old_days()
            # 重置窗口价格列表
            self.anchor_window_prices = []

    def _recent_range_and_atr(self, n: int) -> Tuple[float, float]:
        """计算最近 n 日的真实波幅范围 & ATR。"""
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
        return rng, float(atr_val)

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

    def _trim_old_days(self) -> None:
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

    def _update_event_block(self, dt: datetime) -> None:
        """
        检查并更新事件阻塞状态。
        重大数据发布前后±15分钟：禁开新仓。
        """
        self.event_block = False

        if not self.event_times:
            return

        current_date = dt.date()

        for event_time, event_name in self.event_times:
            # 计算事件时间（考虑跨日情况）
            event_datetime = datetime.combine(current_date, event_time)

            # 检查是否在事件前后±15分钟内
            time_diff = abs((dt - event_datetime).total_seconds())
            if time_diff <= self.event_block_minutes * 60:
                self.event_block = True
                self.write_log(
                    f"{dt.strftime('%Y-%m-%d %H:%M:%S')} - "
                    f"事件阻塞：{event_name}发布前后±{self.event_block_minutes}分钟，禁止开新仓"
                )
                return

    def _update_volatility_penalty(self, bar: BarData) -> None:
        """
        计算一分钟波动幅度，如果>0.5×ATR，提高入场阈值10-20%。
        仅挂被动单（通过提高入场阈值实现）。
        """
        if not self.am.inited or self.atr_value <= 0:
            self.volatility_penalty = 0.0
            return

        # 计算当前K线的波动幅度
        if self.last_bar_high > 0 and self.last_bar_low > 0:
            # 使用上一根K线的波动幅度
            bar_range = self.last_bar_high - self.last_bar_low
        else:
            # 首次计算，使用当前K线
            bar_range = bar.high_price - bar.low_price

        # 计算波动幅度相对于ATR的倍数
        volatility_mult = bar_range / self.atr_value if self.atr_value > 0 else 0.0

        # 如果波动幅度>0.5×ATR，应用惩罚
        if volatility_mult > self.volatility_threshold_mult:
            # 线性插值计算惩罚比例：波动越大，惩罚越大
            # 假设波动在0.5-1.0×ATR之间，惩罚从10%到20%
            excess_vol = volatility_mult - self.volatility_threshold_mult
            max_excess = 0.5  # 假设1.0×ATR为最大参考值
            penalty_ratio = min(
                self.volatility_penalty_max,
                self.volatility_penalty_min +
                (excess_vol / max_excess) * (self.volatility_penalty_max - self.volatility_penalty_min)
            )
            self.volatility_penalty = penalty_ratio

            self.write_log(
                f"{bar.datetime.strftime('%Y-%m-%d %H:%M:%S')} - "
                f"波动过滤：一分钟波动={bar_range:.2f}，ATR倍数={volatility_mult:.2f}，"
                f"提高入场阈值{self.volatility_penalty*100:.1f}%，仅挂被动单"
            )
        else:
            self.volatility_penalty = 0.0

    def _update_trailing_stop(self, bar: BarData) -> None:
        """
        更新浮盈追踪止盈：Trail在[1.2, 1.6]×ATR之间。
        当价格达到浮盈时，动态调整追踪止盈触发价。
        """
        if not self.am.inited or self.atr_value <= 0:
            return

        current_price = bar.close_price

        # 多头持仓的追踪止盈
        if self.pos > 0 and self.entry_price_long > 0:
            # 更新持仓期间最高价
            if current_price > self.highest_price_long:
                self.highest_price_long = current_price

            # 计算当前浮盈
            profit = self.highest_price_long - self.entry_price_long

            # 如果浮盈达到最小追踪止盈触发条件（1.2×ATR）
            min_trail_threshold = self.trail_multiplier_min * self.atr_value
            if profit >= min_trail_threshold:
                # 计算追踪止盈触发价：最高价 - Trail×ATR
                # Trail在[1.2, 1.6]之间，根据浮盈大小动态调整
                if profit >= self.trail_multiplier_max * self.atr_value:
                    # 浮盈足够大，使用最大追踪距离
                    trail_distance = self.trail_multiplier_max * self.atr_value
                else:
                    # 浮盈在最小和最大之间，线性插值
                    progress = (profit - min_trail_threshold) / (
                        (self.trail_multiplier_max - self.trail_multiplier_min) * self.atr_value
                    )
                    trail_distance = (
                        self.trail_multiplier_min +
                        progress * (self.trail_multiplier_max - self.trail_multiplier_min)
                    ) * self.atr_value

                new_trail_price = self.highest_price_long - trail_distance

                # 只有当新的追踪止盈价高于之前的时，才更新（只能向上移动）
                if new_trail_price > self.trail_price_long:
                    self.trail_price_long = new_trail_price

                    # 如果当前价格触及追踪止盈，触发平仓
                    if current_price <= self.trail_price_long:
                        self.write_log(
                            f"{bar.datetime.strftime('%Y-%m-%d %H:%M:%S')} - "
                            f"多头追踪止盈触发: price={current_price:.2f}, "
                            f"trail_price={self.trail_price_long:.2f}, "
                            f"最高价={self.highest_price_long:.2f}"
                        )
                        self._flatten_all(current_price)
                    else:
                        # 更新追踪止盈单
                        self.cancel_all()
                        qty = abs(self.pos)
                        self.sell(self.sl_price_long, qty, stop=True)  # 保留止损
                        self.sell(self.trail_price_long, qty, stop=True)  # 追踪止盈
                        self.sell(self.tp_price_long, qty)  # 保留目标止盈
        
        # 空头持仓的追踪止盈
        elif self.pos < 0 and self.entry_price_short > 0:
            # 更新持仓期间最低价
            if current_price < self.lowest_price_short:
                self.lowest_price_short = current_price

            # 计算当前浮盈
            profit = self.entry_price_short - self.lowest_price_short

            # 如果浮盈达到最小追踪止盈触发条件（1.2×ATR）
            min_trail_threshold = self.trail_multiplier_min * self.atr_value
            if profit >= min_trail_threshold:
                # 计算追踪止盈触发价：最低价 + Trail×ATR
                if profit >= self.trail_multiplier_max * self.atr_value:
                    trail_distance = self.trail_multiplier_max * self.atr_value
                else:
                    progress = (profit - min_trail_threshold) / (
                        (self.trail_multiplier_max - self.trail_multiplier_min) * self.atr_value
                    )
                    trail_distance = (
                        self.trail_multiplier_min +
                        progress * (self.trail_multiplier_max - self.trail_multiplier_min)
                    ) * self.atr_value

                new_trail_price = self.lowest_price_short + trail_distance

                # 只有当新的追踪止盈价低于之前的时，才更新（只能向下移动）
                if new_trail_price < self.trail_price_short or self.trail_price_short == 0:
                    self.trail_price_short = new_trail_price

                    # 如果当前价格触及追踪止盈，触发平仓
                    if current_price >= self.trail_price_short:
                        self.write_log(
                            f"{bar.datetime.strftime('%Y-%m-%d %H:%M:%S')} - "
                            f"空头追踪止盈触发: price={current_price:.2f}, "
                            f"trail_price={self.trail_price_short:.2f}, "
                            f"最低价={self.lowest_price_short:.2f}"
                        )
                        self._flatten_all(current_price)
                    else:
                        # 更新追踪止盈单
                        self.cancel_all()
                        qty = abs(self.pos)
                        self.cover(self.sl_price_short, qty, stop=True)  # 保留止损
                        self.cover(self.trail_price_short, qty, stop=True)  # 追踪止盈
                        self.cover(self.tp_price_short, qty)  # 保留目标止盈

    def write_log(self, msg: str) -> None:
        self.logger.debug(msg)
