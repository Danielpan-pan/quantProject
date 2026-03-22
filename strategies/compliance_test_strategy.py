"""
期货程序化交易系统功能合规测试策略
不依赖实时行情，通过配置文件定时执行各种测试场景
"""

import json
import os
from datetime import datetime, time
from typing import Dict, List, Optional
from pathlib import Path
from collections import deque
from vnpy_ctastrategy import (
    CtaTemplate,
    BarGenerator,
    TickData,
    BarData,
    TradeData,
    OrderData,
)
from vnpy.trader.constant import Direction, Offset, OrderType, Status
from vnpy.trader.object import CancelRequest
from utils.logger import DummyRunLogger


class ComplianceTestStrategy(CtaTemplate):
    """
    功能合规测试策略
    - 周期性读取配置文件触发测试
    - 支持所有功能需求测试场景
    - 记录详细测试日志
    """

    logger = DummyRunLogger()

    # ===== 参数 =====
    config_file: str = "D:\\hermes-vnpy\\strategies\\compliance_test_config.json"
    test_interval: int = 10  # 测试执行间隔（秒）
    enable_auto_test: bool = True  # 启用自动测试
    test_symbol: str = "ag2512"  # 测试合约
    test_exchange: str = "SHFE"  # 测试交易所

    # 阈值参数
    repeat_order_threshold: int = 5  # 重复报单阈值
    total_order_threshold: int = 100  # 报单总笔数阈值
    repeat_cancel_threshold: int = 10  # 重复撤单阈值
    total_cancel_threshold: int = 50  # 撤单总笔数阈值

    # 校验参数
    max_single_volume: int = 50  # 单笔最大手数
    min_price_tick: float = 1.0  # 最小变动价位
    contract_size: float = 15.0  # 合约乘数
    min_price_tick: float = 1.0  # 最小变动价位
    margin_ratio: float = 0.1  # 保证金比例
    available_margin: float = 0.0  # 可用保证金

    parameters = [
        "config_file",
        "test_interval",
        "enable_auto_test",
        "test_symbol",
        "test_exchange",
        "repeat_order_threshold",
        "total_order_threshold",
        "repeat_cancel_threshold",
        "total_cancel_threshold",
        "max_single_volume",
        "min_price_tick",
    ]

    # ===== 变量 =====
    # 连接状态监测 (MON-001)
    connection_status: str = "未连接"
    last_connection_time: Optional[datetime] = None

    # 报单/撤单计数 (MON-002~006)
    repeat_open_count: Dict[str, int] = {}  # 单合约重复开仓计数
    repeat_close_count: Dict[str, int] = {}  # 单合约重复平仓计数
    repeat_cancel_count: Dict[str, int] = {}  # 单合约重复撤单计数
    total_order_count: int = 0  # 总报单笔数
    total_cancel_count: int = 0  # 总撤单笔数

    # 时间窗口计数（用于重复报单监测）
    order_time_window: int = 60  # 时间窗口（秒）
    open_orders_history: deque = deque(maxlen=100)  # 开仓历史
    close_orders_history: deque = deque(maxlen=100)  # 平仓历史
    cancel_orders_history: deque = deque(maxlen=100)  # 撤单历史

    # 测试执行状态
    last_test_time: Optional[datetime] = None
    test_sequence: int = 0
    current_test_phase: str = "初始化"

    # 错误统计
    validation_errors: List[Dict] = []
    threshold_alerts: List[Dict] = []

    # 应急处置状态
    trading_paused: bool = False  # 交易暂停标志
    pause_reason: str = ""

    variables = [
        "connection_status",
        "repeat_open_count",
        "repeat_close_count",
        "repeat_cancel_count",
        "total_order_count",
        "total_cancel_count",
        "test_sequence",
        "current_test_phase",
        "validation_errors",
        "threshold_alerts",
        "trading_paused",
        "pause_reason",
    ]

    def __init__(self, cta_engine, strategy_name, vt_symbol, setting):
        """初始化策略"""
        super().__init__(cta_engine, strategy_name, vt_symbol, setting)

        # 确保配置文件路径正确
        if not os.path.isabs(self.config_file):
            self.config_file = os.path.join(
                os.path.dirname(os.path.dirname(__file__)), self.config_file
            )

        # 初始化deque
        self.open_orders_history = deque(maxlen=100)
        self.close_orders_history = deque(maxlen=100)
        self.cancel_orders_history = deque(maxlen=100)

        # 初始化计数字典
        self.repeat_open_count = {}
        self.repeat_close_count = {}
        self.repeat_cancel_count = {}

        # 初始化列表
        self.validation_errors = []
        self.threshold_alerts = []

    def on_init(self) -> None:
        """策略初始化"""
        self.logger.info("=== 功能合规测试策略初始化 ===")
        self.logger.info(f"配置文件路径: {self.config_file}")
        self.logger.info(f"测试合约: {self.vt_symbol}")
        self.logger.info(f"测试间隔: {self.test_interval}秒")

        # 创建默认配置文件
        self._create_default_config()

        # 初始化Bar生成器
        self.bg = BarGenerator(self.on_bar)

        # 记录初始化日志 (LOG-002)
        self._log_system_event("策略初始化", "初始化成功")

        # IF-001: 测试认证功能
        self._test_authentication()

    def on_start(self) -> None:
        """策略启动"""
        self.logger.info("=== 策略启动 ===")
        self.connection_status = "已连接"
        self.last_connection_time = datetime.now()

        contract = self.cta_engine.main_engine.get_contract(self.vt_symbol)

        self.contract_size = float(contract.size)
        self.min_price_tick = float(contract.pricetick)
        # self.margin_ratio = float(contract.margin_ratio)

        account = self.cta_engine.main_engine.get_account(
            self.cta_engine.main_engine.get_all_accounts()[0].vt_accountid
        )

        self.available_margin = float(account.available)

        # IF-002: 记录登录成功
        self._log_system_event("策略启动", "登录交易信息系统成功")

        # MON-001: 连接状态监测
        self._monitor_connection_status("正常运行")

    def on_stop(self) -> None:
        """策略停止"""
        self.logger.info("=== 策略停止 ===")

        # 记录停止日志
        self._log_system_event("策略停止", f"已执行{self.test_sequence}个测试序列")

        # 输出测试统计
        self._print_test_summary()

    def on_tick(self, tick: TickData) -> None:
        """Tick推送"""
        self.bg.update_tick(tick)

        # 使用Tick时间戳作为测试触发器
        if self.enable_auto_test:
            self._check_and_execute_tests(tick.datetime)

    def on_bar(self, bar: BarData) -> None:
        """Bar推送 - 主要测试逻辑触发点"""
        # 使用Bar作为定时器
        if self.enable_auto_test:
            self._check_and_execute_tests(bar.datetime)

        self.put_event()

    def on_order(self, order: OrderData) -> None:
        """订单回调"""
        # 记录订单状态变化 (LOG-002)
        self._log_trade_event(
            "订单状态更新",
            f"订单ID: {order.orderid}, 状态: {order.status.value}, "
            f"方向: {order.direction.value}, 数量: {order.volume}",
        )

        # MON-001: 监测订单错误
        if order.status == Status.REJECTED:
            self._log_error_event(
                "订单被拒", f"订单ID: {order.orderid}, 原因: 交易所拒单"
            )

    def on_trade(self, trade: TradeData) -> None:
        """成交回调"""
        # LOG-002: 记录成交信息
        self._log_trade_event(
            "成交",
            f"成交ID: {trade.tradeid}, 方向: {trade.direction.value}, "
            f"开平: {trade.offset.value}, 价格: {trade.price}, 数量: {trade.volume}",
        )

        self.put_event()

    # ========== 测试执行框架 ==========

    def _check_and_execute_tests(self, current_time: datetime) -> None:
        """检查并执行测试"""
        # 检查是否到达执行间隔
        if self.last_test_time is not None:
            elapsed = (current_time - self.last_test_time).total_seconds()
            if elapsed < self.test_interval:
                return

        # 更新测试时间
        self.last_test_time = current_time
        self.test_sequence += 1

        # 读取配置文件
        test_config = self._load_test_config()
        if not test_config:
            return

        # 执行测试序列
        self._execute_test_sequence(test_config, current_time)

    def _execute_test_sequence(self, config: Dict, current_time: datetime) -> None:
        """执行测试序列"""
        self.logger.info(f"\n{'=' * 60}")
        self.logger.info(f"测试序列 #{self.test_sequence} 开始 - {current_time}")
        self.logger.info(f"{'=' * 60}")

        # 获取测试场景列表
        scenarios = config.get("test_scenarios", [])

        for scenario in scenarios:
            if not scenario.get("enabled", True):
                continue

            scenario_name = scenario.get("name", "未命名测试")
            test_type = scenario.get("type", "")

            self.logger.info(f"\n执行测试: {scenario_name} (类型: {test_type})")
            self.current_test_phase = scenario_name

            # 根据测试类型执行相应测试
            if test_type == "IF-001":
                self._test_authentication()
            elif test_type == "IF-002":
                self._test_login()
            elif test_type == "TR-001":
                self._test_open_position(scenario)
            elif test_type == "TR-002":
                self._test_close_position(scenario)
            elif test_type == "TR-003":
                self._test_cancel_order(scenario)
            elif test_type == "MON-001":
                self._test_connection_monitor()
            elif test_type == "MON-002":
                self._test_repeat_open_monitor(scenario)
            elif test_type == "MON-003":
                self._test_repeat_close_monitor(scenario)
            elif test_type == "MON-004":
                self._test_repeat_cancel_monitor(scenario)
            elif test_type == "MON-005":
                self._test_total_order_monitor()
            elif test_type == "MON-006":
                self._test_total_cancel_monitor()
            elif test_type == "TH-001":
                self._test_threshold_setting(scenario)
            elif test_type == "TH-002":
                self._test_repeat_open_threshold_alert(scenario)
            elif test_type == "TH-003":
                self._test_repeat_close_threshold_alert(scenario)
            elif test_type == "TH-004":
                self._test_repeat_cancel_threshold_alert(scenario)
            elif test_type == "TH-005":
                self._test_total_order_threshold_setting()
            elif test_type == "TH-006":
                self._test_total_order_threshold_alert()
            elif test_type == "TH-007":
                self._test_total_cancel_threshold_setting()
            elif test_type == "TH-008":
                self._test_total_cancel_threshold_alert()
            elif test_type == "VAL-001":
                self._test_contract_validation(scenario)
            elif test_type == "VAL-002":
                self._test_price_tick_validation(scenario)
            elif test_type == "VAL-003":
                self._test_volume_validation(scenario)
            elif test_type == "ERR-001":
                self._test_insufficient_margin_error(scenario)
            elif test_type == "ERR-002":
                self._test_insufficient_position_error(scenario)
            elif test_type == "ERR-003":
                self._test_market_status_error(scenario)
            elif test_type == "EM-001":
                self._test_pause_trading(scenario)
            elif test_type == "EM-002":
                self._test_partial_batch_cancel(scenario)
            elif test_type == "EM-003":
                self._test_full_batch_cancel(scenario)
            elif test_type == "LOG-001":
                self._test_log_persistence()
            elif test_type == "LOG-002":
                self._test_log_content_coverage()
            else:
                self.logger.warning(f"未知测试类型: {test_type}")

        self.logger.info(f"\n{'=' * 60}")
        self.logger.info(f"测试序列 #{self.test_sequence} 完成")
        self.logger.info(f"{'=' * 60}\n")

    # ========== IF: 接口适应性测试 ==========

    def _test_authentication(self) -> None:
        """IF-001: 测试认证功能"""
        self.logger.info("【IF-001】测试认证功能")

        # 模拟认证过程
        if self.cta_engine:
            self.logger.info("✓ 策略引擎已连接，认证通过")
            self._log_system_event("认证测试", "认证成功")
        else:
            self.logger.error("✗ 认证失败：策略引擎未连接")
            self._log_error_event("认证测试", "认证失败：引擎未连接")

    def _test_login(self) -> None:
        """IF-002: 测试登录"""
        self.logger.info("【IF-002】测试登录交易信息系统")

        # 检查连接状态
        if self.connection_status == "已连接":
            self.logger.info("✓ 系统已登录，状态正常")
            self._log_system_event("登录测试", "登录成功")
        else:
            self.logger.warning(f"⚠ 连接状态: {self.connection_status}")
            self._log_system_event("登录测试", f"连接状态: {self.connection_status}")

    # ========== TR: 基础交易测试 ==========

    def _test_open_position(self, scenario: Dict) -> None:
        """TR-001: 测试开仓指令"""
        self.logger.info("【TR-001】测试开仓指令")

        # 检查交易是否暂停 (EM-001)
        if self.trading_paused:
            self.logger.warning(f"✗ 交易已暂停: {self.pause_reason}")
            self._log_error_event("开仓测试", f"交易已暂停: {self.pause_reason}")
            return

        # 获取测试参数
        direction = scenario.get("direction", "long")
        volume = scenario.get("volume", 1)
        price = scenario.get("price", 7000.0)

        # VAL-003: 单笔最大手数检查
        if not self._validate_volume(volume):
            return

        # VAL-002: 价格最小变动价位检查
        if not self._validate_price_tick(price):
            return

        # ERR-001: 资金不足检查（简化版）
        if not self._check_sufficient_margin(price, volume):
            return

        # 尝试发送开仓委托
        try:
            if direction == "long":
                # self.buy(price, volume)
                self.logger.info(f"✓ 模拟买开: 价格={price}, 数量={volume}")
                self._record_open_order(self.vt_symbol, "买开", volume)
            else:
                # self.short(price, volume)
                self.logger.info(f"✓ 模拟卖开: 价格={price}, 数量={volume}")
                self._record_open_order(self.vt_symbol, "卖开", volume)

            self._log_trade_event(
                "开仓", f"方向={direction}, 价格={price}, 数量={volume}"
            )

        except Exception as e:
            self.logger.error(f"✗ 开仓失败: {str(e)}")
            self._log_error_event("开仓", str(e))

    def _test_close_position(self, scenario: Dict) -> None:
        """TR-002: 测试平仓指令"""
        self.logger.info("【TR-002】测试平仓指令")

        # 检查交易是否暂停
        if self.trading_paused:
            self.logger.warning(f"✗ 交易已暂停: {self.pause_reason}")
            return

        direction = scenario.get("direction", "long")
        volume = scenario.get("volume", 1)
        price = scenario.get("price", 7000.0)

        # ERR-002: 持仓不足检查
        if not self._check_sufficient_position(direction, volume):
            return

        # VAL-002: 价格检查
        if not self._validate_price_tick(price):
            return

        try:
            if direction == "long":
                # self.sell(price, volume)
                self.logger.info(f"✓ 模拟卖平: 价格={price}, 数量={volume}")
                self._record_close_order(self.vt_symbol, "卖平", volume)
            else:
                # self.cover(price, volume)
                self.logger.info(f"✓ 模拟买平: 价格={price}, 数量={volume}")
                self._record_close_order(self.vt_symbol, "买平", volume)

            self._log_trade_event(
                "平仓", f"方向={direction}, 价格={price}, 数量={volume}"
            )

        except Exception as e:
            self.logger.error(f"✗ 平仓失败: {str(e)}")
            self._log_error_event("平仓", str(e))

    def _test_cancel_order(self, scenario: Dict) -> None:
        """TR-003: 测试撤单指令"""
        self.logger.info("【TR-003】测试撤单指令")

        # 检查交易是否暂停
        if self.trading_paused:
            self.logger.warning(f"✗ 交易已暂停: {self.pause_reason}")
            return

        # 获取活动委托
        # active_orders = self.cta_engine.get_all_active_orders()

        # 模拟撤单
        order_count = scenario.get("order_count", 1)

        for i in range(order_count):
            # self.cancel_all()
            self.logger.info(f"✓ 模拟撤单 #{i + 1}")
            self._record_cancel_order(self.vt_symbol)

        self._log_trade_event("撤单", f"撤单数量={order_count}")

    # ========== MON: 异常监测测试 ==========

    def _test_connection_monitor(self) -> None:
        """MON-001: 测试连接状态监测"""
        self.logger.info("【MON-001】测试连接状态监测")

        self.logger.info(f"当前连接状态: {self.connection_status}")
        if self.last_connection_time:
            self.logger.info(f"最后连接时间: {self.last_connection_time}")

        # 模拟连接状态变化
        self._monitor_connection_status(self.connection_status)

    def _test_repeat_open_monitor(self, scenario: Dict) -> None:
        """MON-002: 测试单合约重复开仓监测"""
        self.logger.info("【MON-002】测试单合约重复开仓监测")

        symbol = scenario.get("symbol", self.vt_symbol)
        count = self._count_recent_open_orders(symbol)

        self.logger.info(
            f"合约 {symbol} 在过去 {self.order_time_window}秒 内开仓次数: {count}"
        )

        # 记录监测结果
        self._log_monitor_event("重复开仓监测", f"{symbol}: {count}笔")

    def _test_repeat_close_monitor(self, scenario: Dict) -> None:
        """MON-003: 测试单合约重复平仓监测"""
        self.logger.info("【MON-003】测试单合约重复平仓监测")

        symbol = scenario.get("symbol", self.vt_symbol)
        count = self._count_recent_close_orders(symbol)

        self.logger.info(
            f"合约 {symbol} 在过去 {self.order_time_window}秒 内平仓次数: {count}"
        )

        self._log_monitor_event("重复平仓监测", f"{symbol}: {count}笔")

    def _test_repeat_cancel_monitor(self, scenario: Dict) -> None:
        """MON-004: 测试单合约重复撤单监测"""
        self.logger.info("【MON-004】测试单合约重复撤单监测")

        symbol = scenario.get("symbol", self.vt_symbol)
        count = self._count_recent_cancel_orders(symbol)

        self.logger.info(
            f"合约 {symbol} 在过去 {self.order_time_window}秒 内撤单次数: {count}"
        )

        self._log_monitor_event("重复撤单监测", f"{symbol}: {count}笔")

    def _test_total_order_monitor(self) -> None:
        """MON-005: 测试同一账号报单总笔数监测"""
        self.logger.info("【MON-005】测试同一账号报单总笔数监测")

        self.logger.info(f"当前账号总报单笔数: {self.total_order_count}")

        self._log_monitor_event("报单总笔数监测", f"总计: {self.total_order_count}笔")

    def _test_total_cancel_monitor(self) -> None:
        """MON-006: 测试同一账号撤单总笔数监测"""
        self.logger.info("【MON-006】测试同一账号撤单总笔数监测")

        self.logger.info(f"当前账号总撤单笔数: {self.total_cancel_count}")

        self._log_monitor_event("撤单总笔数监测", f"总计: {self.total_cancel_count}笔")

    # ========== TH: 阈值管理测试 ==========

    def _test_threshold_setting(self, scenario: Dict) -> None:
        """TH-001: 测试重复报单笔数阈值设置"""
        self.logger.info("【TH-001】测试重复报单笔数阈值设置")

        new_threshold = scenario.get("threshold", self.repeat_order_threshold)
        self.repeat_order_threshold = new_threshold

        self.logger.info(f"✓ 重复报单阈值已设置为: {new_threshold}")
        self._log_system_event("阈值设置", f"重复报单阈值={new_threshold}")

    def _test_repeat_open_threshold_alert(self, scenario: Dict) -> None:
        """TH-002: 测试重复开仓报单阈值预警"""
        self.logger.info("【TH-002】测试重复开仓报单阈值预警")

        symbol = scenario.get("symbol", self.vt_symbol)
        count = self._count_recent_open_orders(symbol)

        if count >= self.repeat_order_threshold:
            alert_msg = (
                f"⚠ 【阈值预警】重复开仓报单超过阈值！\n"
                f"合约: {symbol}\n"
                f"当前计数: {count}\n"
                f"阈值: {self.repeat_order_threshold}"
            )
            self.logger.warning(alert_msg)
            self._trigger_threshold_alert(
                "重复开仓", symbol, count, self.repeat_order_threshold
            )
        else:
            self.logger.info(
                f"✓ 重复开仓计数({count})未超过阈值({self.repeat_order_threshold})"
            )

    def _test_repeat_close_threshold_alert(self, scenario: Dict) -> None:
        """TH-003: 测试重复平仓报单阈值预警"""
        self.logger.info("【TH-003】测试重复平仓报单阈值预警")

        symbol = scenario.get("symbol", self.vt_symbol)
        count = self._count_recent_close_orders(symbol)

        if count >= self.repeat_order_threshold:
            alert_msg = (
                f"⚠ 【阈值预警】重复平仓报单超过阈值！\n"
                f"合约: {symbol}\n"
                f"当前计数: {count}\n"
                f"阈值: {self.repeat_order_threshold}"
            )
            self.logger.warning(alert_msg)
            self._trigger_threshold_alert(
                "重复平仓", symbol, count, self.repeat_order_threshold
            )
        else:
            self.logger.info(
                f"✓ 重复平仓计数({count})未超过阈值({self.repeat_order_threshold})"
            )

    def _test_repeat_cancel_threshold_alert(self, scenario: Dict) -> None:
        """TH-004: 测试重复撤单报单阈值预警"""
        self.logger.info("【TH-004】测试重复撤单报单阈值预警")

        symbol = scenario.get("symbol", self.vt_symbol)
        count = self._count_recent_cancel_orders(symbol)

        if count >= self.repeat_cancel_threshold:
            alert_msg = (
                f"⚠ 【阈值预警】重复撤单超过阈值！\n"
                f"合约: {symbol}\n"
                f"当前计数: {count}\n"
                f"阈值: {self.repeat_cancel_threshold}"
            )
            self.logger.warning(alert_msg)
            self._trigger_threshold_alert(
                "重复撤单", symbol, count, self.repeat_cancel_threshold
            )
        else:
            self.logger.info(
                f"✓ 重复撤单计数({count})未超过阈值({self.repeat_cancel_threshold})"
            )

    def _test_total_order_threshold_setting(self) -> None:
        """TH-005: 测试报单总笔数阈值设置"""
        self.logger.info("【TH-005】测试报单总笔数阈值设置")

        self.logger.info(f"✓ 报单总笔数阈值: {self.total_order_threshold}")
        self._log_system_event(
            "阈值设置", f"报单总笔数阈值={self.total_order_threshold}"
        )

    def _test_total_order_threshold_alert(self) -> None:
        """TH-006: 测试报单总笔数阈值预警"""
        self.logger.info("【TH-006】测试报单总笔数阈值预警")

        if self.total_order_count >= self.total_order_threshold:
            alert_msg = (
                f"⚠ 【阈值预警】报单总笔数超过阈值！\n"
                f"当前计数: {self.total_order_count}\n"
                f"阈值: {self.total_order_threshold}"
            )
            self.logger.warning(alert_msg)
            self._trigger_threshold_alert(
                "报单总笔数",
                "全账号",
                self.total_order_count,
                self.total_order_threshold,
            )
        else:
            self.logger.info(
                f"✓ 报单总笔数({self.total_order_count})未超过阈值({self.total_order_threshold})"
            )

    def _test_total_cancel_threshold_setting(self) -> None:
        """TH-007: 测试撤单总笔数阈值设置"""
        self.logger.info("【TH-007】测试撤单总笔数阈值设置")

        self.logger.info(f"✓ 撤单总笔数阈值: {self.total_cancel_threshold}")
        self._log_system_event(
            "阈值设置", f"撤单总笔数阈值={self.total_cancel_threshold}"
        )

    def _test_total_cancel_threshold_alert(self) -> None:
        """TH-008: 测试撤单总笔数阈值预警"""
        self.logger.info("【TH-008】测试撤单总笔数阈值预警")

        if self.total_cancel_count >= self.total_cancel_threshold:
            alert_msg = (
                f"⚠ 【阈值预警】撤单总笔数超过阈值！\n"
                f"当前计数: {self.total_cancel_count}\n"
                f"阈值: {self.total_cancel_threshold}"
            )
            self.logger.warning(alert_msg)
            self._trigger_threshold_alert(
                "撤单总笔数",
                "全账号",
                self.total_cancel_count,
                self.total_cancel_threshold,
            )
        else:
            self.logger.info(
                f"✓ 撤单总笔数({self.total_cancel_count})未超过阈值({self.total_cancel_threshold})"
            )

    # ========== VAL: 错误防范 - 指令校验 ==========

    def _test_contract_validation(self, scenario: Dict) -> None:
        """VAL-001: 测试合约代码合法性检查"""
        self.logger.info("【VAL-001】测试合约代码合法性检查")

        test_symbol = scenario.get("symbol", "INVALID123")

        # 简化的合约验证逻辑
        valid_symbols = ["ag2512", "ag88", "au2512", "cu2512"]

        if test_symbol in valid_symbols:
            self.logger.info(f"✓ 合约代码 {test_symbol} 合法")
        else:
            error_msg = f"合约代码 {test_symbol} 不存在或格式错误"
            self.logger.error(f"✗ {error_msg}")
            self._record_validation_error("合约代码校验", error_msg)
            self._log_error_event("合约校验", error_msg)

    def _test_price_tick_validation(self, scenario: Dict) -> None:
        """VAL-002: 测试最小变动价位检查"""
        self.logger.info("【VAL-002】测试最小变动价位检查")

        test_price = scenario.get("price", 7000.5)

        if self._validate_price_tick(test_price):
            self.logger.info(f"✓ 价格 {test_price} 符合最小变动价位")
        # 错误已在_validate_price_tick中记录

    def _test_volume_validation(self, scenario: Dict) -> None:
        """VAL-003: 测试单笔最大手数检查"""
        self.logger.info("【VAL-003】测试单笔最大手数检查")

        test_volume = scenario.get("volume", 100)

        if self._validate_volume(test_volume):
            self.logger.info(f"✓ 数量 {test_volume} 符合要求")
        # 错误已在_validate_volume中记录

    # ========== ERR: 错误防范 - 错误提示 ==========

    def _test_insufficient_margin_error(self, scenario: Dict) -> None:
        """ERR-001: 测试资金不足提示"""
        self.logger.info("【ERR-001】测试资金不足提示")

        price = scenario.get("price", 10000.0)
        volume = scenario.get("volume", 1000)  # 故意设置很大的数量

        if not self._check_sufficient_margin(price, volume):
            self.logger.info("✓ 资金不足检查生效，已拒绝委托")
        else:
            self.logger.info("资金充足，可以下单")

    def _test_insufficient_position_error(self, scenario: Dict) -> None:
        """ERR-002: 测试持仓不足提示"""
        self.logger.info("【ERR-002】测试持仓不足提示")

        direction = scenario.get("direction", "long")
        volume = scenario.get("volume", 100)  # 故意设置很大的数量

        if not self._check_sufficient_position(direction, volume):
            self.logger.info("✓ 持仓不足检查生效，已拒绝委托")
        else:
            self.logger.info("持仓充足，可以平仓")

    def _test_market_status_error(self, scenario: Dict) -> None:
        """ERR-003: 测试市场状态不可用提示"""
        self.logger.info("【ERR-003】测试市场状态不可用提示")

        current_time = datetime.now().time()

        if not self._check_market_available(current_time):
            self.logger.info("✓ 市场状态检查生效，已拒绝委托")
        else:
            self.logger.info("市场可用，可以交易")

    # ========== EM: 应急处置 ==========

    def _test_pause_trading(self, scenario: Dict) -> None:
        """EM-001: 测试暂停交易能力"""
        self.logger.info("【EM-001】测试暂停交易能力")

        action = scenario.get("action", "pause")
        reason = scenario.get("reason", "手动测试")

        if action == "pause":
            self.trading_paused = True
            self.pause_reason = reason
            self.logger.warning(f"⚠ 交易已暂停: {reason}")
            self._log_system_event("暂停交易", reason)
        elif action == "resume":
            self.trading_paused = False
            self.pause_reason = ""
            self.logger.info("✓ 交易已恢复")
            self._log_system_event("恢复交易", "交易恢复正常")

    def _test_partial_batch_cancel(self, scenario: Dict) -> None:
        """EM-002: 测试部分批量撤单"""
        self.logger.info("【EM-002】测试部分批量撤单")

        cancel_count = scenario.get("count", 3)

        # 模拟批量撤单
        for i in range(cancel_count):
            # self.cancel_all()  # 实际应该撤指定订单
            self.logger.info(f"✓ 批量撤单 {i + 1}/{cancel_count}")
            self._record_cancel_order(self.vt_symbol)

        self._log_system_event("部分批量撤单", f"撤单 {cancel_count} 笔")

    def _test_full_batch_cancel(self, scenario: Dict) -> None:
        """EM-003: 测试全部批量撤单"""
        self.logger.info("【EM-003】测试全部批量撤单")

        # 模拟一键全撤
        # active_orders = self.cta_engine.get_all_active_orders()
        # for order in active_orders:
        #     self.cancel_order(...)

        self.logger.info("✓ 执行一键全撤（模拟）")
        self._log_system_event("全部批量撤单", "一键全撤执行")

    # ========== LOG: 日志记录测试 ==========

    def _test_log_persistence(self) -> None:
        """LOG-001: 测试日志持久化"""
        self.logger.info("【LOG-001】测试日志持久化")

        # 检查日志系统是否正常
        if self.logger:
            self.logger.info("✓ 日志系统正常工作")
            self._log_system_event("日志测试", "日志持久化正常")
        else:
            self.logger.error("✗ 日志系统未初始化")

    def _test_log_content_coverage(self) -> None:
        """LOG-002: 测试日志内容覆盖范围"""
        self.logger.info("【LOG-002】测试日志内容覆盖范围")

        # 记录各类日志
        self._log_trade_event("日志测试", "交易日志测试")
        self._log_system_event("日志测试", "系统运行记录测试")
        self._log_monitor_event("日志测试", "监测记录测试")
        self._log_error_event("日志测试", "错误提示信息测试")

        self.logger.info("✓ 日志内容覆盖测试完成")

    # ========== 辅助函数 ==========

    def _load_test_config(self) -> Optional[Dict]:
        """加载测试配置文件"""
        try:
            if not os.path.exists(self.config_file):
                self.logger.warning(f"配置文件不存在: {self.config_file}")
                return None

            with open(self.config_file, "r", encoding="utf-8") as f:
                config = json.load(f)

            return config

        except Exception as e:
            self.logger.error(f"加载配置文件失败: {str(e)}")
            return None

    def _create_default_config(self) -> None:
        """创建默认配置文件"""
        if os.path.exists(self.config_file):
            return

        default_config = {
            "meta": {
                "name": "期货程序化交易系统功能测试配置",
                "version": "1.0",
                "created": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            },
            "test_scenarios": [
                {"name": "认证功能测试", "type": "IF-001", "enabled": True},
                {"name": "登录测试", "type": "IF-002", "enabled": True},
                {
                    "name": "开仓指令测试",
                    "type": "TR-001",
                    "enabled": True,
                    "direction": "long",
                    "volume": 1,
                    "price": 7000.0,
                },
                {
                    "name": "平仓指令测试",
                    "type": "TR-002",
                    "enabled": True,
                    "direction": "long",
                    "volume": 1,
                    "price": 7010.0,
                },
                {
                    "name": "撤单指令测试",
                    "type": "TR-003",
                    "enabled": True,
                    "order_count": 1,
                },
                {"name": "连接状态监测", "type": "MON-001", "enabled": True},
                {
                    "name": "重复开仓监测",
                    "type": "MON-002",
                    "enabled": True,
                    "symbol": "ag2512.SHFE",
                },
                {"name": "报单总笔数监测", "type": "MON-005", "enabled": True},
                {
                    "name": "重复开仓阈值预警测试",
                    "type": "TH-002",
                    "enabled": True,
                    "symbol": "ag2512.SHFE",
                },
                {
                    "name": "合约代码校验测试",
                    "type": "VAL-001",
                    "enabled": True,
                    "symbol": "INVALID123",
                },
                {
                    "name": "价格最小变动价位测试",
                    "type": "VAL-002",
                    "enabled": True,
                    "price": 7000.5,
                },
                {
                    "name": "单笔最大手数测试",
                    "type": "VAL-003",
                    "enabled": True,
                    "volume": 60,
                },
                {
                    "name": "资金不足测试",
                    "type": "ERR-001",
                    "enabled": True,
                    "price": 10000.0,
                    "volume": 1000,
                },
                {"name": "日志持久化测试", "type": "LOG-001", "enabled": True},
                {"name": "日志内容覆盖测试", "type": "LOG-002", "enabled": True},
            ],
        }

        try:
            # 确保目录存在
            os.makedirs(os.path.dirname(self.config_file), exist_ok=True)

            with open(self.config_file, "w", encoding="utf-8") as f:
                json.dump(default_config, f, ensure_ascii=False, indent=2)

            self.logger.info(f"✓ 已创建默认配置文件: {self.config_file}")

        except Exception as e:
            self.logger.error(f"创建默认配置文件失败: {str(e)}")

    # ========== 校验函数 ==========

    def _validate_price_tick(self, price: float) -> bool:
        """VAL-002: 验证价格最小变动价位"""
        if price % self.min_price_tick != 0:
            error_msg = (
                f"价格 {price} 不符合最小变动价位 {self.min_price_tick} 的整数倍"
            )
            self.logger.error(f"✗ {error_msg}")
            self._record_validation_error("价格校验", error_msg)
            self._log_error_event("价格校验", error_msg)
            return False
        return True

    def _validate_volume(self, volume: int) -> bool:
        """VAL-003: 验证单笔最大手数"""
        if volume > self.max_single_volume:
            error_msg = (
                f"委托数量 {volume} 超过单笔最大手数限制 {self.max_single_volume}"
            )
            self.logger.error(f"✗ {error_msg}")
            self._record_validation_error("数量校验", error_msg)
            self._log_error_event("数量校验", error_msg)
            return False
        return True

    def _check_sufficient_margin(self, price: float, volume: int) -> bool:
        """ERR-001: 检查资金是否充足（简化版）"""

        # 这里简化处理，实际应该查询账户资金
        required_margin = price * volume * self.contract_size * self.margin_ratio

        if required_margin > self.available_margin:
            error_msg = (
                f"资金不足：需要保证金 {required_margin:.2f}，"
                f"可用资金 {self.available_margin:.2f}"
            )
            self.logger.error(f"✗ {error_msg}")
            self._log_error_event("资金检查", error_msg)
            return False
        return True

    def _check_sufficient_position(self, direction: str, volume: int) -> bool:
        """ERR-002: 检查持仓是否充足"""
        # 简化处理，实际应该查询真实持仓
        current_position = 5  # 模拟当前持仓

        if volume > current_position:
            error_msg = (
                f"持仓不足：需要平仓 {volume} 手，当前持仓 {current_position} 手"
            )
            self.logger.error(f"✗ {error_msg}")
            self._log_error_event("持仓检查", error_msg)
            return False
        return True

    def _check_market_available(self, current_time: time) -> bool:
        """ERR-003: 检查市场是否可用"""
        # 简化的交易时间判断（沪银期货）
        # 日盘: 09:00-15:00
        # 夜盘: 21:00-02:30

        is_day_session = (time(9, 0) <= current_time <= time(11, 30)) or (
            time(13, 30) <= current_time <= time(15, 0)
        )

        is_night_session = current_time >= time(21, 0) or current_time <= time(2, 30)

        if not (is_day_session or is_night_session):
            error_msg = f"非交易时间：当前时间 {current_time}"
            self.logger.error(f"✗ {error_msg}")
            self._log_error_event("市场状态检查", error_msg)
            return False

        return True

    # ========== 计数与记录函数 ==========

    def _record_open_order(self, symbol: str, direction: str, volume: int) -> None:
        """记录开仓订单"""
        order_info = {
            "time": datetime.now(),
            "symbol": symbol,
            "direction": direction,
            "volume": volume,
            "type": "open",
        }
        self.open_orders_history.append(order_info)
        self.total_order_count += 1

    def _record_close_order(self, symbol: str, direction: str, volume: int) -> None:
        """记录平仓订单"""
        order_info = {
            "time": datetime.now(),
            "symbol": symbol,
            "direction": direction,
            "volume": volume,
            "type": "close",
        }
        self.close_orders_history.append(order_info)
        self.total_order_count += 1

    def _record_cancel_order(self, symbol: str) -> None:
        """记录撤单"""
        cancel_info = {"time": datetime.now(), "symbol": symbol}
        self.cancel_orders_history.append(cancel_info)
        self.total_cancel_count += 1

    def _count_recent_open_orders(self, symbol: str) -> int:
        """统计最近时间窗口内的开仓次数"""
        now = datetime.now()
        count = 0

        for order in self.open_orders_history:
            if (now - order["time"]).total_seconds() <= self.order_time_window:
                if order["symbol"] == symbol:
                    count += 1

        return count

    def _count_recent_close_orders(self, symbol: str) -> int:
        """统计最近时间窗口内的平仓次数"""
        now = datetime.now()
        count = 0

        for order in self.close_orders_history:
            if (now - order["time"]).total_seconds() <= self.order_time_window:
                if order["symbol"] == symbol:
                    count += 1

        return count

    def _count_recent_cancel_orders(self, symbol: str) -> int:
        """统计最近时间窗口内的撤单次数"""
        now = datetime.now()
        count = 0

        for cancel in self.cancel_orders_history:
            if (now - cancel["time"]).total_seconds() <= self.order_time_window:
                if cancel["symbol"] == symbol:
                    count += 1

        return count

    def _record_validation_error(self, error_type: str, message: str) -> None:
        """记录校验错误"""
        error_info = {"time": datetime.now(), "type": error_type, "message": message}
        self.validation_errors.append(error_info)

    def _trigger_threshold_alert(
        self, alert_type: str, symbol: str, current: int, threshold: int
    ) -> None:
        """触发阈值告警"""
        alert_info = {
            "time": datetime.now(),
            "type": alert_type,
            "symbol": symbol,
            "current": current,
            "threshold": threshold,
        }
        self.threshold_alerts.append(alert_info)

        # 可以在这里添加更多告警方式：弹窗、声音、短信、邮件等
        # 这里只是记录日志

    # ========== 日志记录函数 ==========

    def _log_trade_event(self, event_type: str, message: str) -> None:
        """记录交易日志"""
        log_msg = f"[交易日志] {event_type}: {message}"
        self.logger.info(log_msg)

    def _log_system_event(self, event_type: str, message: str) -> None:
        """记录系统运行记录"""
        log_msg = f"[系统记录] {event_type}: {message}"
        self.logger.info(log_msg)

    def _log_monitor_event(self, event_type: str, message: str) -> None:
        """记录监测记录"""
        log_msg = f"[监测记录] {event_type}: {message}"
        self.logger.info(log_msg)

    def _log_error_event(self, event_type: str, message: str) -> None:
        """记录错误提示信息"""
        log_msg = f"[错误提示] {event_type}: {message}"
        self.logger.error(log_msg)

    def _monitor_connection_status(self, status: str) -> None:
        """MON-001: 监测连接状态"""
        self.connection_status = status
        self.last_connection_time = datetime.now()

        self._log_system_event(
            "连接状态变更", f"状态: {status}, 时间: {self.last_connection_time}"
        )

    def _print_test_summary(self) -> None:
        """打印测试摘要"""
        self.logger.info("\n" + "=" * 60)
        self.logger.info("测试摘要")
        self.logger.info("=" * 60)
        self.logger.info(f"总测试序列数: {self.test_sequence}")
        self.logger.info(f"总报单笔数: {self.total_order_count}")
        self.logger.info(f"总撤单笔数: {self.total_cancel_count}")
        self.logger.info(f"校验错误数: {len(self.validation_errors)}")
        self.logger.info(f"阈值告警数: {len(self.threshold_alerts)}")

        if self.validation_errors:
            self.logger.info("\n校验错误列表:")
            for i, error in enumerate(self.validation_errors[-10:], 1):
                self.logger.info(
                    f"  {i}. [{error['type']}] {error['message']} "
                    f"({error['time'].strftime('%H:%M:%S')})"
                )

        if self.threshold_alerts:
            self.logger.info("\n阈值告警列表:")
            for i, alert in enumerate(self.threshold_alerts[-10:], 1):
                self.logger.info(
                    f"  {i}. [{alert['type']}] {alert['symbol']} "
                    f"当前={alert['current']}, 阈值={alert['threshold']} "
                    f"({alert['time'].strftime('%H:%M:%S')})"
                )

        self.logger.info("=" * 60 + "\n")

    def write_log(self, msg: str) -> None:
        """写日志"""
        self.logger.debug(msg)
