from abc import ABC, abstractmethod
from copy import copy
from typing import Any, cast
from collections.abc import Callable
from enum import Enum

from vnpy.trader.constant import Interval, Direction, Offset
from vnpy.trader.object import BarData, TickData, OrderData, TradeData
from vnpy_ctastrategy.base import StopOrder, EngineType


class StrategyMode(str, Enum):
    """策略运行模式"""
    BACKTEST = "backtest"  # 回测模式
    LIVE_TEST = "live_test"  # 实盘（测试）模式
    LIVE = "live"  # 实盘模式


class CtaTemplate(ABC):
    """"""

    author: str = ""
    parameters: list = []
    variables: list = []

    # 策略运行模式参数
    mode: str = StrategyMode.LIVE_TEST.value  # 默认回测模式
    fallback_contract_size: float = 1.0  # 回测模式下的默认合约乘数
    account_equity: float = 1_000_000.0  # 回测和实盘测试模式下的初始账户资金

    def __init__(
        self,
        cta_engine: Any,
        strategy_name: str,
        vt_symbol: str,
        setting: dict,
    ) -> None:
        """"""
        self.cta_engine: Any = cta_engine
        self.strategy_name: str = strategy_name
        self.vt_symbol: str = vt_symbol

        self.inited: bool = False
        self.trading: bool = False
        self.pos: int = 0

        # Copy a new variables list here to avoid duplicate insert when multiple
        # strategy instances are created with the same strategy class.
        self.variables = copy(self.variables)
        self.variables.insert(0, "inited")
        self.variables.insert(1, "trading")
        self.variables.insert(2, "pos")

        # 实盘测试和回测模式下维护的模拟账户资金
        self._sim_account_equity: float = 0.0
        # 实盘测试模式下维护的模拟持仓
        self._sim_pos: int = 0

        self.update_setting(setting)

        # 初始化账户资金（回测和实盘测试模式）
        if self.mode in [StrategyMode.BACKTEST.value, StrategyMode.LIVE_TEST.value]:
            self._sim_account_equity = self.account_equity

    def update_setting(self, setting: dict) -> None:
        """
        Update strategy parameter wtih value in setting dict.
        """
        for name in self.parameters:
            if name in setting:
                setattr(self, name, setting[name])

    @classmethod
    def get_class_parameters(cls) -> dict:
        """
        Get default parameters dict of strategy class.
        """
        class_parameters: dict = {}
        for name in cls.parameters:
            class_parameters[name] = getattr(cls, name)
        return class_parameters

    def get_parameters(self) -> dict:
        """
        Get strategy parameters dict.
        """
        strategy_parameters: dict = {}
        for name in self.parameters:
            strategy_parameters[name] = getattr(self, name)
        return strategy_parameters

    def get_variables(self) -> dict:
        """
        Get strategy variables dict.
        """
        strategy_variables: dict = {}
        for name in self.variables:
            strategy_variables[name] = getattr(self, name)
        return strategy_variables

    def get_data(self) -> dict:
        """
        Get strategy data.
        """
        strategy_data: dict = {
            "strategy_name": self.strategy_name,
            "vt_symbol": self.vt_symbol,
            "class_name": self.__class__.__name__,
            "author": self.author,
            "parameters": self.get_parameters(),
            "variables": self.get_variables(),
        }
        return strategy_data

    @abstractmethod
    def on_init(self) -> None:
        """
        Callback when strategy is inited.
        """
        return

    def on_start(self) -> None:
        """
        Callback when strategy is started.
        """
        return

    def on_stop(self) -> None:
        """
        Callback when strategy is stopped.
        """
        return

    def on_tick(self, tick: TickData) -> None:
        """
        Callback of new tick data update.
        """
        return

    def on_bar(self, bar: BarData) -> None:
        """
        Callback of new bar data update.
        """
        return

    def on_trade(self, trade: TradeData) -> None:
        """
        Callback of new trade data update.
        """
        return

    def on_order(self, order: OrderData) -> None:
        """
        Callback of new order data update.
        """
        return

    def on_stop_order(self, stop_order: StopOrder) -> None:
        """
        Callback of stop order update.
        """
        return

    def buy(
        self,
        price: float,
        volume: float,
        stop: bool = False,
        lock: bool = False,
        net: bool = False,
    ) -> list:
        """
        Send buy order to open a long position.
        """
        return self.send_order(
            Direction.LONG, Offset.OPEN, price, volume, stop, lock, net
        )

    def sell(
        self,
        price: float,
        volume: float,
        stop: bool = False,
        lock: bool = False,
        net: bool = False,
    ) -> list:
        """
        Send sell order to close a long position.
        """
        return self.send_order(
            Direction.SHORT, Offset.CLOSE, price, volume, stop, lock, net
        )

    def short(
        self,
        price: float,
        volume: float,
        stop: bool = False,
        lock: bool = False,
        net: bool = False,
    ) -> list:
        """
        Send short order to open as short position.
        """
        return self.send_order(
            Direction.SHORT, Offset.OPEN, price, volume, stop, lock, net
        )

    def cover(
        self,
        price: float,
        volume: float,
        stop: bool = False,
        lock: bool = False,
        net: bool = False,
    ) -> list:
        """
        Send cover order to close a short position.
        """
        return self.send_order(
            Direction.LONG, Offset.CLOSE, price, volume, stop, lock, net
        )

    def send_order(
        self,
        direction: Direction,
        offset: Offset,
        price: float,
        volume: float,
        stop: bool = False,
        lock: bool = False,
        net: bool = False,
    ) -> list:
        """
        Send a new order.
        在实盘（测试）模式下，禁止实际交易，只记录 log 和更新模拟变量。
        """
        # 实盘（测试）模式下禁止实际交易
        if self.mode == StrategyMode.LIVE_TEST.value:
            # 记录交易意图
            direction_str = "做多" if direction == Direction.LONG else "做空"
            offset_str = "开仓" if offset == Offset.OPEN else "平仓"
            action_str = f"{direction_str}{offset_str}"

            self.write_log(
                f"[实盘测试模式] {action_str} - 价格: {price}, 数量: {volume}, "
                f"当前持仓: {self._sim_pos}, 账户资金: {self._sim_account_equity:.2f}"
            )

            # 更新模拟持仓
            if direction == Direction.LONG:
                if offset == Offset.OPEN:
                    self._sim_pos += int(volume)
                else:  # CLOSE
                    self._sim_pos -= int(volume)
            else:  # SHORT
                if offset == Offset.OPEN:
                    self._sim_pos -= int(volume)
                else:  # CLOSE
                    self._sim_pos += int(volume)

            # 更新模拟账户资金（简化处理，实际可能需要考虑更多因素）
            contract_size = self.get_contract_size()
            cost = price * volume * contract_size
            # 简化处理：开仓扣除，平仓增加（实际应该考虑盈亏）
            if offset == Offset.OPEN:
                self._sim_account_equity -= cost
            else:
                self._sim_account_equity += cost

            # 记录更新后的状态
            self.write_log(
                f"[实盘测试模式] 交易后 - 持仓: {self._sim_pos}, "
                f"账户资金: {self._sim_account_equity:.2f}"
            )

            return []  # 返回空列表，表示没有实际订单

        # 回测和实盘模式正常交易
        if self.trading:
            vt_orderids: list = self.cta_engine.send_order(
                self, direction, offset, price, volume, stop, lock, net
            )
            return vt_orderids
        else:
            return []

    def cancel_order(self, vt_orderid: str) -> None:
        """
        Cancel an existing order.
        在实盘（测试）模式下，禁止实际撤单，只记录 log。
        """
        if self.mode == StrategyMode.LIVE_TEST.value:
            self.write_log(f"[实盘测试模式] 撤单请求 - 订单ID: {vt_orderid}（已禁止实际撤单）")
            return

        if self.trading:
            self.cta_engine.cancel_order(self, vt_orderid)

    def cancel_all(self) -> None:
        """
        Cancel all orders sent by strategy.
        在实盘（测试）模式下，禁止实际撤单，只记录 log。
        """
        if self.mode == StrategyMode.LIVE_TEST.value:
            self.write_log("[实盘测试模式] 撤销所有订单请求（已禁止实际撤单）")
            return

        if self.trading:
            self.cta_engine.cancel_all(self)

    def write_log(self, msg: str) -> None:
        """
        Write a log message.
        """
        self.cta_engine.write_log(msg, self)

    def get_engine_type(self) -> EngineType:
        """
        Return whether the cta_engine is backtesting or live trading.
        """
        return cast(EngineType, self.cta_engine.get_engine_type())

    def get_pricetick(self) -> float:
        """
        Return pricetick data of trading contract.
        """
        return cast(float, self.cta_engine.get_pricetick(self))

    def get_size(self) -> int:
        """
        Return size data of trading contract.
        """
        return cast(int, self.cta_engine.get_size(self))

    def get_contract_size(self) -> float:
        """
        根据模式获取合约乘数。
        - 回测模式：使用默认设置（fallback_contract_size）
        - 实盘（测试）和实盘模式：从 engine 获取
        """
        if self.mode == StrategyMode.BACKTEST.value:
            return self.fallback_contract_size
        else:
            # 实盘（测试）和实盘模式从 engine 获取
            try:
                contract = self.cta_engine.main_engine.get_contract(self.vt_symbol)
                if contract and hasattr(contract, "size"):
                    return float(contract.size)
                else:
                    # 如果获取失败，尝试使用 get_size 方法
                    size = self.get_size()
                    if size:
                        return float(size)
                    else:
                        self.write_log(f"无法获取合约乘数，使用默认值: {self.fallback_contract_size}")
                        return self.fallback_contract_size
            except Exception as e:
                self.write_log(f"获取合约乘数失败: {e}，使用默认值: {self.fallback_contract_size}")
                return self.fallback_contract_size

    def get_account_balance(self) -> float:
        """
        根据模式获取账户资金。
        - 实盘模式：从 engine 获取
        - 回测和实盘（测试）模式：使用自己维护的资金变量
        """
        if self.mode == StrategyMode.LIVE.value:
            # 实盘模式从 engine 获取
            try:
                accounts = self.cta_engine.main_engine.get_all_accounts()
                if accounts:
                    account = self.cta_engine.main_engine.get_account(accounts[0].vt_accountid)
                    if account:
                        # 优先使用 available，如果没有则使用 balance
                        if hasattr(account, "available"):
                            return float(account.available)
                        elif hasattr(account, "balance"):
                            return float(account.balance)
                        elif hasattr(account, "total_equity"):
                            return float(account.total_equity)
                self.write_log("未找到账户信息，使用预设资金")
                return self.account_equity
            except Exception as e:
                self.write_log(f"获取账户资金失败: {e}，使用预设资金: {self.account_equity}")
                return self.account_equity
        else:
            # 回测和实盘（测试）模式使用自己维护的资金
            return self._sim_account_equity

    def update_account_balance(
        self,
        price: float,
        volume: float,
        direction: Direction,
        offset: Offset,
        commission: float = 0.0
    ) -> None:
        """
        在回测和实盘（测试）模式下更新账户资金。

        Args:
            price: 成交价格
            volume: 成交数量
            direction: 方向（LONG/SHORT）
            offset: 开平仓（OPEN/CLOSE）
            commission: 手续费（可选）
        """
        if self.mode not in [StrategyMode.BACKTEST.value, StrategyMode.LIVE_TEST.value]:
            return

        contract_size = self.get_contract_size()
        cost = price * volume * contract_size

        # 计算资金变化
        if direction == Direction.LONG and offset == Offset.OPEN:
            # 开多仓：扣除资金
            self._sim_account_equity -= (cost + commission)
        elif direction == Direction.LONG and offset == Offset.CLOSE:
            # 平空仓：增加资金
            self._sim_account_equity += (cost - commission)
        elif direction == Direction.SHORT and offset == Offset.OPEN:
            # 开空仓：扣除保证金（简化处理，实际可能需要考虑保证金比例）
            self._sim_account_equity -= (cost + commission)
        elif direction == Direction.SHORT and offset == Offset.CLOSE:
            # 平多仓：增加资金
            self._sim_account_equity += (cost - commission)

        # 确保资金不为负
        if self._sim_account_equity < 0:
            self.write_log(f"警告：账户资金为负: {self._sim_account_equity}")
            self._sim_account_equity = 0.0

    def on_trade_update_balance(self, trade: TradeData, commission: float = 0.0) -> None:
        """
        在 on_trade 回调中调用此方法，用于在回测和实盘（测试）模式下更新账户资金。
        注意：在回测模式下，资金通常由回测引擎自动管理，此方法主要用于实盘测试模式。

        Args:
            trade: 成交数据
            commission: 手续费（可选）
        """
        if self.mode in [StrategyMode.BACKTEST.value, StrategyMode.LIVE_TEST.value]:
            self.update_account_balance(
                trade.price,
                trade.volume,
                trade.direction,
                trade.offset,
                commission
            )

    def load_bar(
        self,
        days: int,
        interval: Interval = Interval.MINUTE,
        callback: Callable | None = None,
        use_database: bool = False,
    ) -> None:
        """
        Load historical bar data for initializing strategy.
        """
        if not callback:
            callback = self.on_bar

        bars: list[BarData] = self.cta_engine.load_bar(
            self.vt_symbol, days, interval, callback, use_database
        )

        for bar in bars:
            callback(bar)

    def load_tick(self, days: int) -> None:
        """
        Load historical tick data for initializing strategy.
        """
        ticks: list[TickData] = self.cta_engine.load_tick(
            self.vt_symbol, days, self.on_tick
        )

        for tick in ticks:
            self.on_tick(tick)

    def put_event(self) -> None:
        """
        Put an strategy data event for ui update.
        """
        if self.inited:
            self.cta_engine.put_strategy_event(self)

    def send_email(self, msg: str) -> None:
        """
        Send email to default receiver.
        """
        if self.inited:
            self.cta_engine.send_email(msg, self)

    def sync_data(self) -> None:
        """
        Sync strategy variables value into disk storage.
        """
        if self.trading:
            self.cta_engine.sync_strategy_data(self)


class CtaSignal(ABC):
    """"""

    def __init__(self) -> None:
        """"""
        self.signal_pos = 0

    def on_tick(self, tick: TickData) -> None:
        """
        Callback of new tick data update.
        """
        return

    @abstractmethod
    def on_bar(self, bar: BarData) -> None:
        """
        Callback of new bar data update.
        """
        return

    def set_signal_pos(self, pos: int) -> None:
        """"""
        self.signal_pos = pos

    def get_signal_pos(self) -> Any:
        """"""
        return self.signal_pos


class TargetPosTemplate(CtaTemplate):
    """"""

    tick_add = 1

    last_tick: TickData = None
    last_bar: BarData = None
    target_pos = 0

    def __init__(
        self, cta_engine: Any, strategy_name: str, vt_symbol: str, setting: dict
    ) -> None:
        """"""
        super().__init__(cta_engine, strategy_name, vt_symbol, setting)

        self.active_orderids: list[str] = []
        self.cancel_orderids: list[str] = []

        self.variables.append("target_pos")

    def on_tick(self, tick: TickData) -> None:
        """
        Callback of new tick data update.
        """
        self.last_tick = tick

    def on_bar(self, bar: BarData) -> None:
        """
        Callback of new bar data update.
        """
        self.last_bar = bar

    def on_order(self, order: OrderData) -> None:
        """
        Callback of new order data update.
        """
        vt_orderid: str = order.vt_orderid

        if not order.is_active():
            if vt_orderid in self.active_orderids:
                self.active_orderids.remove(vt_orderid)

            if vt_orderid in self.cancel_orderids:
                self.cancel_orderids.remove(vt_orderid)

    def check_order_finished(self) -> bool:
        """"""
        if self.active_orderids:
            return False
        else:
            return True

    def set_target_pos(self, target_pos: int) -> None:
        """"""
        self.target_pos = target_pos
        self.trade()

    def trade(self) -> None:
        """"""
        if not self.check_order_finished():
            self.cancel_old_order()
        else:
            self.send_new_order()

    def cancel_old_order(self) -> None:
        """"""
        for vt_orderid in self.active_orderids:
            if vt_orderid not in self.cancel_orderids:
                self.cancel_order(vt_orderid)
                self.cancel_orderids.append(vt_orderid)

    def send_new_order(self) -> None:
        """"""
        pos_change = self.target_pos - self.pos
        if not pos_change:
            return

        long_price = 0
        short_price = 0

        if self.last_tick:
            if pos_change > 0:
                long_price = self.last_tick.ask_price_1 + self.tick_add
                if self.last_tick.limit_up:
                    long_price = min(long_price, self.last_tick.limit_up)
            else:
                short_price = self.last_tick.bid_price_1 - self.tick_add
                if self.last_tick.limit_down:
                    short_price = max(short_price, self.last_tick.limit_down)

        else:
            if pos_change > 0:
                long_price = self.last_bar.close_price + self.tick_add
            else:
                short_price = self.last_bar.close_price - self.tick_add

        if self.get_engine_type() == EngineType.BACKTESTING:
            if pos_change > 0:
                vt_orderids: list[str] = self.buy(long_price, abs(pos_change))
            else:
                vt_orderids = self.short(short_price, abs(pos_change))
            self.active_orderids.extend(vt_orderids)

        else:
            if self.active_orderids:
                return

            if pos_change > 0:
                if self.pos < 0:
                    if pos_change < abs(self.pos):
                        vt_orderids = self.cover(long_price, pos_change)
                    else:
                        vt_orderids = self.cover(long_price, abs(self.pos))
                else:
                    vt_orderids = self.buy(long_price, abs(pos_change))
            else:
                if self.pos > 0:
                    if abs(pos_change) < self.pos:
                        vt_orderids = self.sell(short_price, abs(pos_change))
                    else:
                        vt_orderids = self.sell(short_price, abs(self.pos))
                else:
                    vt_orderids = self.short(short_price, abs(pos_change))
            self.active_orderids.extend(vt_orderids)
