"""
风控管理模块
实现监测、阈值管理、预警等功能
"""

import time
from datetime import datetime, timedelta
from typing import Dict, List, Optional
from collections import defaultdict, deque
from dataclasses import dataclass, field
from enum import Enum
import logging


class AlertLevel(str, Enum):
    """告警级别"""

    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


class AlertType(str, Enum):
    """告警类型"""

    REPEAT_OPEN = "repeat_open"  # 重复开仓
    REPEAT_CLOSE = "repeat_close"  # 重复平仓
    REPEAT_CANCEL = "repeat_cancel"  # 重复撤单
    TOTAL_ORDER = "total_order"  # 报单总量
    TOTAL_CANCEL = "total_cancel"  # 撤单总量
    CONNECTION = "connection"  # 连接状态
    VALIDATION = "validation"  # 校验错误
    SYSTEM = "system"  # 系统错误


@dataclass
class Alert:
    """告警信息"""

    alert_id: str
    alert_type: AlertType
    level: AlertLevel
    message: str
    timestamp: datetime
    account: Optional[str] = None
    symbol: Optional[str] = None
    current_value: Optional[float] = None
    threshold: Optional[float] = None
    extra_data: Dict = field(default_factory=dict)


@dataclass
class ThresholdConfig:
    """阈值配置"""

    # 重复报单类阈值
    repeat_open_threshold: int = 10  # 单合约重复开仓阈值
    repeat_close_threshold: int = 10  # 单合约重复平仓阈值
    repeat_cancel_threshold: int = 10  # 单合约重复撤单阈值
    repeat_time_window: int = 60  # 重复报单统计时间窗口（秒）

    # 报单/撤单总量类阈值
    total_order_threshold: int = 1000  # 单账号报单总笔数阈值
    total_cancel_threshold: int = 500  # 单账号撤单总笔数阈值
    total_time_period: str = "day"  # 统计周期：day, hour

    # 单笔限制
    max_order_volume: int = 100  # 单笔最大手数

    # 是否启用
    enabled: bool = True


@dataclass
class ValidationRule:
    """校验规则"""

    check_contract: bool = True  # 合约代码合法性检查
    check_tick_size: bool = True  # 最小变动价位检查
    check_max_volume: bool = True  # 单笔最大手数检查
    check_balance: bool = True  # 资金检查
    check_position: bool = True  # 持仓检查
    check_market_status: bool = True  # 市场状态检查


class OrderMonitor:
    """订单监测器"""

    def __init__(self, time_window: int = 60):
        self.time_window = time_window
        # 按账号+合约维度统计重复报单
        self.open_orders: Dict[str, deque] = defaultdict(lambda: deque())
        self.close_orders: Dict[str, deque] = defaultdict(lambda: deque())
        self.cancel_orders: Dict[str, deque] = defaultdict(lambda: deque())

        # 按账号维度统计总量
        self.total_orders: Dict[str, int] = defaultdict(int)
        self.total_cancels: Dict[str, int] = defaultdict(int)

        # 统计周期重置时间
        self.reset_time: Dict[str, datetime] = {}

    def _clean_old_records(self, records: deque, current_time: datetime):
        """清理超出时间窗口的记录"""
        cutoff_time = current_time - timedelta(seconds=self.time_window)
        while records and records[0] < cutoff_time:
            records.popleft()

    def record_open_order(self, account: str, symbol: str) -> int:
        """记录开仓指令"""
        key = f"{account}:{symbol}"
        current_time = datetime.now()
        self.open_orders[key].append(current_time)
        self._clean_old_records(self.open_orders[key], current_time)
        return len(self.open_orders[key])

    def record_close_order(self, account: str, symbol: str) -> int:
        """记录平仓指令"""
        key = f"{account}:{symbol}"
        current_time = datetime.now()
        self.close_orders[key].append(current_time)
        self._clean_old_records(self.close_orders[key], current_time)
        return len(self.close_orders[key])

    def record_cancel_order(self, account: str, symbol: str) -> int:
        """记录撤单指令"""
        key = f"{account}:{symbol}"
        current_time = datetime.now()
        self.cancel_orders[key].append(current_time)
        self._clean_old_records(self.cancel_orders[key], current_time)
        return len(self.cancel_orders[key])

    def record_total_order(self, account: str) -> int:
        """记录报单总量"""
        self.total_orders[account] += 1
        return self.total_orders[account]

    def record_total_cancel(self, account: str) -> int:
        """记录撤单总量"""
        self.total_cancels[account] += 1
        return self.total_cancels[account]

    def get_repeat_open_count(self, account: str, symbol: str) -> int:
        """获取重复开仓次数"""
        key = f"{account}:{symbol}"
        current_time = datetime.now()
        self._clean_old_records(self.open_orders[key], current_time)
        return len(self.open_orders[key])

    def get_repeat_close_count(self, account: str, symbol: str) -> int:
        """获取重复平仓次数"""
        key = f"{account}:{symbol}"
        current_time = datetime.now()
        self._clean_old_records(self.close_orders[key], current_time)
        return len(self.close_orders[key])

    def get_repeat_cancel_count(self, account: str, symbol: str) -> int:
        """获取重复撤单次数"""
        key = f"{account}:{symbol}"
        current_time = datetime.now()
        self._clean_old_records(self.cancel_orders[key], current_time)
        return len(self.cancel_orders[key])

    def reset_daily_stats(self, account: str):
        """重置每日统计"""
        self.total_orders[account] = 0
        self.total_cancels[account] = 0
        self.reset_time[account] = datetime.now()

    def get_statistics(self, account: Optional[str] = None) -> Dict:
        """获取统计信息"""
        if account:
            return {
                "account": account,
                "total_orders": self.total_orders.get(account, 0),
                "total_cancels": self.total_cancels.get(account, 0),
                "reset_time": self.reset_time.get(account),
            }
        else:
            return {
                "accounts": {
                    acc: {
                        "total_orders": self.total_orders.get(acc, 0),
                        "total_cancels": self.total_cancels.get(acc, 0),
                    }
                    for acc in set(
                        list(self.total_orders.keys()) + list(self.total_cancels.keys())
                    )
                }
            }


class RiskManager:
    """风控管理器"""

    def __init__(
        self,
        config: Optional[ThresholdConfig] = None,
        validation_rule: Optional[ValidationRule] = None,
    ):
        self.config = config or ThresholdConfig()
        self.validation_rule = validation_rule or ValidationRule()
        self.monitor = OrderMonitor(time_window=self.config.repeat_time_window)

        # 告警记录
        self.alerts: List[Alert] = []
        self.alert_callbacks: List = []

        # 交易控制
        self.trading_enabled = True
        self.trading_paused_reason = ""

        # 合约信息缓存
        self.contracts: Dict = {}

        # 日志
        self.logger = logging.getLogger("RiskManager")

    def update_config(self, config: ThresholdConfig):
        """更新阈值配置"""
        self.config = config
        self.monitor.time_window = config.repeat_time_window
        self.logger.info(f"风控配置已更新: {config}")

    def update_validation_rule(self, rule: ValidationRule):
        """更新校验规则"""
        self.validation_rule = rule
        self.logger.info(f"校验规则已更新: {rule}")

    def add_alert_callback(self, callback):
        """添加告警回调"""
        self.alert_callbacks.append(callback)

    def _trigger_alert(self, alert: Alert):
        """触发告警"""
        self.alerts.append(alert)
        self.logger.warning(f"触发告警: {alert.message}")

        # 执行回调
        for callback in self.alert_callbacks:
            try:
                callback(alert)
            except Exception as e:
                self.logger.error(f"告警回调执行失败: {e}")

    def check_repeat_open(
        self, account: str, symbol: str
    ) -> tuple[bool, Optional[Alert]]:
        """检查重复开仓"""
        if not self.config.enabled:
            return True, None

        count = self.monitor.record_open_order(account, symbol)

        if count >= self.config.repeat_open_threshold:
            alert = Alert(
                alert_id=f"repeat_open_{int(time.time())}",
                alert_type=AlertType.REPEAT_OPEN,
                level=AlertLevel.WARNING,
                message=f"重复开仓告警: 账号 {account}, 合约 {symbol}, "
                f"在 {self.config.repeat_time_window}秒内开仓 {count} 次, "
                f"超过阈值 {self.config.repeat_open_threshold}",
                timestamp=datetime.now(),
                account=account,
                symbol=symbol,
                current_value=count,
                threshold=self.config.repeat_open_threshold,
            )
            self._trigger_alert(alert)
            return False, alert

        return True, None

    def check_repeat_close(
        self, account: str, symbol: str
    ) -> tuple[bool, Optional[Alert]]:
        """检查重复平仓"""
        if not self.config.enabled:
            return True, None

        count = self.monitor.record_close_order(account, symbol)

        if count >= self.config.repeat_close_threshold:
            alert = Alert(
                alert_id=f"repeat_close_{int(time.time())}",
                alert_type=AlertType.REPEAT_CLOSE,
                level=AlertLevel.WARNING,
                message=f"重复平仓告警: 账号 {account}, 合约 {symbol}, "
                f"在 {self.config.repeat_time_window}秒内平仓 {count} 次, "
                f"超过阈值 {self.config.repeat_close_threshold}",
                timestamp=datetime.now(),
                account=account,
                symbol=symbol,
                current_value=count,
                threshold=self.config.repeat_close_threshold,
            )
            self._trigger_alert(alert)
            return False, alert

        return True, None

    def check_repeat_cancel(
        self, account: str, symbol: str
    ) -> tuple[bool, Optional[Alert]]:
        """检查重复撤单"""
        if not self.config.enabled:
            return True, None

        count = self.monitor.record_cancel_order(account, symbol)

        if count >= self.config.repeat_cancel_threshold:
            alert = Alert(
                alert_id=f"repeat_cancel_{int(time.time())}",
                alert_type=AlertType.REPEAT_CANCEL,
                level=AlertLevel.WARNING,
                message=f"重复撤单告警: 账号 {account}, 合约 {symbol}, "
                f"在 {self.config.repeat_time_window}秒内撤单 {count} 次, "
                f"超过阈值 {self.config.repeat_cancel_threshold}",
                timestamp=datetime.now(),
                account=account,
                symbol=symbol,
                current_value=count,
                threshold=self.config.repeat_cancel_threshold,
            )
            self._trigger_alert(alert)
            return False, alert

        return True, None

    def check_total_orders(self, account: str) -> tuple[bool, Optional[Alert]]:
        """检查报单总量"""
        if not self.config.enabled:
            return True, None

        count = self.monitor.record_total_order(account)

        if count >= self.config.total_order_threshold:
            alert = Alert(
                alert_id=f"total_order_{int(time.time())}",
                alert_type=AlertType.TOTAL_ORDER,
                level=AlertLevel.WARNING,
                message=f"报单总量告警: 账号 {account}, "
                f"报单总笔数 {count}, 超过阈值 {self.config.total_order_threshold}",
                timestamp=datetime.now(),
                account=account,
                current_value=count,
                threshold=self.config.total_order_threshold,
            )
            self._trigger_alert(alert)
            return False, alert

        return True, None

    def check_total_cancels(self, account: str) -> tuple[bool, Optional[Alert]]:
        """检查撤单总量"""
        if not self.config.enabled:
            return True, None

        count = self.monitor.record_total_cancel(account)

        if count >= self.config.total_cancel_threshold:
            alert = Alert(
                alert_id=f"total_cancel_{int(time.time())}",
                alert_type=AlertType.TOTAL_CANCEL,
                level=AlertLevel.WARNING,
                message=f"撤单总量告警: 账号 {account}, "
                f"撤单总笔数 {count}, 超过阈值 {self.config.total_cancel_threshold}",
                timestamp=datetime.now(),
                account=account,
                current_value=count,
                threshold=self.config.total_cancel_threshold,
            )
            self._trigger_alert(alert)
            return False, alert

        return True, None

    def validate_contract(self, symbol: str) -> tuple[bool, str]:
        """校验合约代码合法性"""
        if not self.validation_rule.check_contract:
            return True, ""

        if not symbol or len(symbol) == 0:
            return False, "合约代码为空"

        # 检查合约是否在缓存中（实际应该查询交易所）
        if symbol not in self.contracts and len(self.contracts) > 0:
            return False, f"合约代码 {symbol} 不存在或未订阅"

        return True, ""

    def validate_price(self, symbol: str, price: float) -> tuple[bool, str]:
        """校验价格最小变动价位"""
        if not self.validation_rule.check_tick_size:
            return True, ""

        contract = self.contracts.get(symbol)
        if not contract:
            # 如果没有合约信息，暂时放行
            return True, ""

        pricetick = contract.get("pricetick", 0.01)
        if price <= 0:
            return False, f"价格必须大于0"

        # 检查价格是否为最小变动价位的整数倍
        remainder = round(price % pricetick, 10)  # 避免浮点精度问题
        if remainder > 0.0000001 and abs(remainder - pricetick) > 0.0000001:
            return False, f"价格 {price} 不符合最小变动价位 {pricetick}"

        return True, ""

    def validate_volume(self, volume: float) -> tuple[bool, str]:
        """校验单笔最大手数"""
        if not self.validation_rule.check_max_volume:
            return True, ""

        if volume <= 0:
            return False, "委托数量必须大于0"

        if volume > self.config.max_order_volume:
            return (
                False,
                f"委托数量 {volume} 超过单笔最大手数限制 {self.config.max_order_volume}",
            )

        return True, ""

    def validate_balance(
        self, account: str, required_margin: float
    ) -> tuple[bool, str]:
        """校验资金充足性"""
        if not self.validation_rule.check_balance:
            return True, ""

        # 这里应该查询实际账户资金，简化处理
        # 实际实现需要从交易引擎获取账户信息
        return True, ""

    def validate_position(
        self, account: str, symbol: str, volume: float
    ) -> tuple[bool, str]:
        """校验持仓充足性（平仓时）"""
        if not self.validation_rule.check_position:
            return True, ""

        # 这里应该查询实际持仓，简化处理
        # 实际实现需要从交易引擎获取持仓信息
        return True, ""

    def validate_market_status(self, symbol: str) -> tuple[bool, str]:
        """校验市场状态"""
        if not self.validation_rule.check_market_status:
            return True, ""

        # 这里应该检查交易时间和市场状态
        # 实际实现需要查询交易日历和行情状态
        current_time = datetime.now().time()

        # 简单的交易时间判断（以期货为例）
        # 上午：9:00-11:30, 下午：13:30-15:00, 夜盘：21:00-次日2:30
        from datetime import time as dt_time

        morning = dt_time(9, 0) <= current_time <= dt_time(11, 30)
        afternoon = dt_time(13, 30) <= current_time <= dt_time(15, 0)
        night = current_time >= dt_time(21, 0) or current_time <= dt_time(2, 30)

        if not (morning or afternoon or night):
            return False, "当前非交易时间"

        return True, ""

    def pause_trading(self, reason: str):
        """暂停交易"""
        self.trading_enabled = False
        self.trading_paused_reason = reason
        self.logger.warning(f"交易已暂停: {reason}")

        alert = Alert(
            alert_id=f"trading_pause_{int(time.time())}",
            alert_type=AlertType.SYSTEM,
            level=AlertLevel.CRITICAL,
            message=f"交易已暂停: {reason}",
            timestamp=datetime.now(),
            extra_data={"reason": reason},
        )
        self._trigger_alert(alert)

    def resume_trading(self):
        """恢复交易"""
        self.trading_enabled = True
        self.trading_paused_reason = ""
        self.logger.info("交易已恢复")

    def is_trading_allowed(self) -> tuple[bool, str]:
        """检查是否允许交易"""
        if not self.trading_enabled:
            return False, self.trading_paused_reason or "交易已暂停"
        return True, ""

    def update_contract(self, symbol: str, contract_data: Dict):
        """更新合约信息"""
        self.contracts[symbol] = contract_data

    def get_alerts(
        self, limit: int = 100, alert_type: Optional[AlertType] = None
    ) -> List[Alert]:
        """获取告警记录"""
        alerts = self.alerts[-limit:]
        if alert_type:
            alerts = [a for a in alerts if a.alert_type == alert_type]
        return list(reversed(alerts))

    def get_statistics(self) -> Dict:
        """获取统计信息"""
        return self.monitor.get_statistics()

    def reset_daily_stats(self, account: str):
        """重置每日统计"""
        self.monitor.reset_daily_stats(account)
        self.logger.info(f"已重置账号 {account} 的每日统计")
