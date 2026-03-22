"""
交易系统主应用程序
集成 Flask WebUI 和 VNPY 交易引擎
"""

import logging
from datetime import datetime
from pathlib import Path
from threading import Lock

from flask import Flask, render_template, request, jsonify
from flask_cors import CORS
from flask_socketio import SocketIO, emit

# VNPY imports
from vnpy.event import EventEngine, Event
from vnpy.trader.engine import MainEngine
from vnpy.trader.object import (
    SubscribeRequest,
    OrderRequest,
    CancelRequest,
    TickData,
    OrderData,
    TradeData,
    PositionData,
    AccountData,
    ContractData,
    LogData,
)
from vnpy.trader.constant import Direction, Offset, OrderType, Exchange, Status
from vnpy.trader.event import (
    EVENT_TICK,
    EVENT_ORDER,
    EVENT_TRADE,
    EVENT_POSITION,
    EVENT_ACCOUNT,
    EVENT_CONTRACT,
    EVENT_LOG,
)
from vnpy_ctp import CtpGateway

# 本地模块
from config_manager import ConfigManager
from risk_manager import RiskManager, ThresholdConfig, ValidationRule, Alert


# 配置日志
# 确保日志目录存在
# 获取当前脚本所在目录
base_dir = Path(__file__).parent
log_dir = base_dir / "logs"
log_dir.mkdir(exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler(log_dir / "trading_webui.log", encoding="utf-8"),
        logging.StreamHandler(),
    ],
)
logger = logging.getLogger("TradingWebUI")


class TradingWebUIApp:
    """交易系统 WebUI 应用"""

    def __init__(self, config_file: str = "config.json"):
        # 如果是相对路径，转换为绝对路径
        config_path = Path(config_file)
        if not config_path.is_absolute():
            config_path = base_dir / config_file

        # 初始化配置
        self.config_manager = ConfigManager(str(config_path))

        # 加载环境变量配置
        self.config_manager.load_from_env()

        # 初始化风控管理器
        risk_config = self.config_manager.get_risk_config()
        validation_config = self.config_manager.get_validation_config()

        threshold_config = ThresholdConfig(**risk_config)
        validation_rule = ValidationRule(**validation_config)

        self.risk_manager = RiskManager(threshold_config, validation_rule)
        self.risk_manager.add_alert_callback(self._on_alert)

        # 初始化 VNPY
        self.event_engine = EventEngine()
        self.main_engine = MainEngine(self.event_engine)
        self.main_engine.add_gateway(CtpGateway)

        # 数据缓存
        self.ticks: dict[str, TickData] = {}
        self.orders: dict[str, OrderData] = {}
        self.trades: dict[str, TradeData] = {}
        self.positions: dict[str, PositionData] = {}
        self.accounts: dict[str, AccountData] = {}
        self.contracts: dict[str, ContractData] = {}

        # 日志缓存
        self.logs: list[dict] = []
        self.max_logs = 1000

        # 交易统计
        self.trade_statistics = {
            "total_trades": 0,
            "total_orders": 0,
            "successful_orders": 0,
            "failed_orders": 0,
            "cancelled_orders": 0,
        }

        # 连接状态
        self.connection_status = {
            "connected": False,
            "td_connected": False,
            "md_connected": False,
            "login_time": None,
            "error_message": "",
        }

        # 线程锁
        self.data_lock = Lock()

        # 订阅的合约
        self.subscribed_symbols: set = set()

        # 注册事件处理
        self._register_event_handlers()

        # 初始化 Flask
        self.flask_app = Flask(
            __name__, template_folder="templates", static_folder="static"
        )
        CORS(self.flask_app)

        # 初始化 SocketIO
        self.socketio = SocketIO(self.flask_app, cors_allowed_origins="*")

        # 注册路由
        self._register_routes()
        self._register_socketio_events()

        logger.info("交易系统 WebUI 应用初始化完成")

    def auto_subscribe_saved_symbols(self):
        """自动订阅保存的合约"""
        subscriptions = self.config_manager.get_subscriptions()
        if not subscriptions:
            logger.info("没有保存的订阅")
            return

        logger.info(f"正在自动订阅 {len(subscriptions)} 个合约...")

        for sub in subscriptions:
            try:
                symbol = sub.get("symbol")
                exchange_str = sub.get("exchange")

                if not symbol or not exchange_str:
                    continue

                exchange = Exchange(exchange_str)
                req = SubscribeRequest(symbol=symbol, exchange=exchange)
                self.main_engine.subscribe(req, "CTP")

                vt_symbol = f"{symbol}.{exchange.value}"
                self.subscribed_symbols.add(vt_symbol)
                logger.info(f"已自动订阅: {vt_symbol}")

            except Exception as e:
                logger.error(f"自动订阅失败 {sub}: {e}")

    def _register_event_handlers(self):
        """注册 VNPY 事件处理器"""
        self.event_engine.register(EVENT_TICK, self._process_tick_event)
        self.event_engine.register(EVENT_ORDER, self._process_order_event)
        self.event_engine.register(EVENT_TRADE, self._process_trade_event)
        self.event_engine.register(EVENT_POSITION, self._process_position_event)
        self.event_engine.register(EVENT_ACCOUNT, self._process_account_event)
        self.event_engine.register(EVENT_CONTRACT, self._process_contract_event)
        self.event_engine.register(EVENT_LOG, self._process_log_event)

    def _process_tick_event(self, event: Event):
        """处理 Tick 事件"""
        tick: TickData = event.data
        with self.data_lock:
            self.ticks[tick.vt_symbol] = tick

        # 通过 WebSocket 推送
        self._emit_tick_update(tick)

    def _process_order_event(self, event: Event):
        """处理订单事件"""
        order: OrderData = event.data
        with self.data_lock:
            self.orders[order.vt_orderid] = order

            # 更新统计
            if order.status == Status.ALLTRADED:
                self.trade_statistics["successful_orders"] += 1
            elif order.status == Status.CANCELLED:
                self.trade_statistics["cancelled_orders"] += 1
            elif order.status == Status.REJECTED:
                self.trade_statistics["failed_orders"] += 1

        # 通过 WebSocket 推送
        self._emit_order_update(order)

    def _process_trade_event(self, event: Event):
        """处理成交事件"""
        trade: TradeData = event.data
        with self.data_lock:
            self.trades[trade.vt_tradeid] = trade
            self.trade_statistics["total_trades"] += 1

        # 通过 WebSocket 推送
        self._emit_trade_update(trade)

    def _process_position_event(self, event: Event):
        """处理持仓事件"""
        position: PositionData = event.data
        with self.data_lock:
            self.positions[position.vt_positionid] = position

        # 通过 WebSocket 推送
        self._emit_position_update(position)

    def _process_account_event(self, event: Event):
        """处理账户事件"""
        account: AccountData = event.data
        with self.data_lock:
            self.accounts[account.vt_accountid] = account

        # 通过 WebSocket 推送
        self._emit_account_update(account)

    def _process_contract_event(self, event: Event):
        """处理合约事件"""
        contract: ContractData = event.data
        with self.data_lock:
            self.contracts[contract.vt_symbol] = contract

            # 更新风控管理器的合约信息
            self.risk_manager.update_contract(
                contract.vt_symbol,
                {
                    "symbol": contract.symbol,
                    "exchange": contract.exchange.value,
                    "name": contract.name,
                    "size": contract.size,
                    "pricetick": contract.pricetick,
                    "min_volume": contract.min_volume,
                    "product": contract.product.value if contract.product else "",
                },
            )

    def _process_log_event(self, event: Event):
        """处理日志事件"""
        log: LogData = event.data
        log_dict = {
            "time": log.time.strftime("%Y-%m-%d %H:%M:%S"),
            "level": log.level.name if hasattr(log.level, "name") else str(log.level),
            "msg": log.msg,
            "gateway_name": log.gateway_name,
        }

        with self.data_lock:
            self.logs.append(log_dict)
            if len(self.logs) > self.max_logs:
                self.logs.pop(0)

        # 通过 WebSocket 推送
        self._emit_log(log_dict)

        # 检查连接状态
        if "交易服务器登录成功" in log.msg or "TD Server login success" in log.msg:
            self.connection_status["td_connected"] = True
            self.connection_status["connected"] = True
            self.connection_status["login_time"] = datetime.now().strftime(
                "%Y-%m-%d %H:%M:%S"
            )
            self._emit_connection_status()

        if "行情服务器登录成功" in log.msg or "MD Server login success" in log.msg:
            self.connection_status["md_connected"] = True
            self._emit_connection_status()

    def _on_alert(self, alert: Alert):
        """告警回调"""
        alert_dict = {
            "alert_id": alert.alert_id,
            "type": alert.alert_type.value,
            "level": alert.level.value,
            "message": alert.message,
            "timestamp": alert.timestamp.strftime("%Y-%m-%d %H:%M:%S"),
            "account": alert.account,
            "symbol": alert.symbol,
            "current_value": alert.current_value,
            "threshold": alert.threshold,
        }

        # 记录日志
        self._add_log("RISK", alert.message)

        # 通过 WebSocket 推送
        self._emit_alert(alert_dict)

    # WebSocket 推送方法
    def _emit_tick_update(self, tick: TickData):
        """推送 Tick 更新"""
        try:
            self.socketio.emit(
                "tick_update",
                {
                    "symbol": tick.vt_symbol,
                    "last_price": tick.last_price,
                    "volume": tick.volume,
                    "open_interest": tick.open_interest,
                    "datetime": tick.datetime.strftime("%Y-%m-%d %H:%M:%S")
                    if tick.datetime
                    else "",
                    "bid_price_1": tick.bid_price_1,
                    "ask_price_1": tick.ask_price_1,
                    "bid_volume_1": tick.bid_volume_1,
                    "ask_volume_1": tick.ask_volume_1,
                },
            )
        except Exception as e:
            logger.error(f"推送 Tick 更新失败: {e}")

    def _emit_order_update(self, order: OrderData):
        """推送订单更新"""
        try:
            self.socketio.emit(
                "order_update",
                {
                    "vt_orderid": order.vt_orderid,
                    "symbol": order.vt_symbol,
                    "direction": order.direction.value,
                    "offset": order.offset.value,
                    "price": order.price,
                    "volume": order.volume,
                    "traded": order.traded,
                    "status": order.status.name,  # 使用枚举名而不是中文值
                    "datetime": order.datetime.strftime("%Y-%m-%d %H:%M:%S")
                    if order.datetime
                    else "",
                },
            )
        except Exception as e:
            logger.error(f"推送订单更新失败: {e}")

    def _emit_trade_update(self, trade: TradeData):
        """推送成交更新"""
        try:
            self.socketio.emit(
                "trade_update",
                {
                    "vt_tradeid": trade.vt_tradeid,
                    "vt_orderid": trade.vt_orderid,
                    "symbol": trade.vt_symbol,
                    "direction": trade.direction.value,
                    "offset": trade.offset.value,
                    "price": trade.price,
                    "volume": trade.volume,
                    "datetime": trade.datetime.strftime("%Y-%m-%d %H:%M:%S")
                    if trade.datetime
                    else "",
                },
            )
        except Exception as e:
            logger.error(f"推送成交更新失败: {e}")

    def _emit_position_update(self, position: PositionData):
        """推送持仓更新"""
        try:
            self.socketio.emit(
                "position_update",
                {
                    "vt_positionid": position.vt_positionid,
                    "symbol": position.vt_symbol,
                    "direction": position.direction.name,  # 使用枚举名而不是中文值
                    "volume": position.volume,
                    "frozen": position.frozen,
                    "price": position.price,
                    "pnl": position.pnl,
                    "yd_volume": position.yd_volume,
                },
            )
        except Exception as e:
            logger.error(f"推送持仓更新失败: {e}")

    def _emit_account_update(self, account: AccountData):
        """推送账户更新"""
        try:
            self.socketio.emit(
                "account_update",
                {
                    "vt_accountid": account.vt_accountid,
                    "balance": account.balance,
                    "frozen": account.frozen,
                    "available": account.available,
                },
            )
        except Exception as e:
            logger.error(f"推送账户更新失败: {e}")

    def _emit_log(self, log_dict: dict):
        """推送日志"""
        try:
            self.socketio.emit("log", log_dict)
        except Exception as e:
            logger.error(f"推送日志失败: {e}")

    def _emit_alert(self, alert_dict: dict):
        """推送告警"""
        try:
            self.socketio.emit("alert", alert_dict)
        except Exception as e:
            logger.error(f"推送告警失败: {e}")

    def _emit_connection_status(self):
        """推送连接状态"""
        try:
            self.socketio.emit("connection_status", self.connection_status)
        except Exception as e:
            logger.error(f"推送连接状态失败: {e}")

    def _add_log(self, level: str, msg: str):
        """添加系统日志"""
        log_dict = {
            "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "level": level,
            "msg": msg,
            "gateway_name": "SYSTEM",
        }

        with self.data_lock:
            self.logs.append(log_dict)
            if len(self.logs) > self.max_logs:
                self.logs.pop(0)

        logger.info(f"[{level}] {msg}")

    # Flask 路由注册
    def _register_routes(self):
        """注册 Flask 路由"""

        @self.flask_app.route("/")
        def index():
            """主页"""
            return render_template("index.html")

        @self.flask_app.route("/api/status")
        def get_status():
            """获取系统状态"""
            return jsonify(
                {
                    "success": True,
                    "data": {
                        "connection": self.connection_status,
                        "trading_enabled": self.risk_manager.trading_enabled,
                        "statistics": self.trade_statistics,
                    },
                }
            )

        @self.flask_app.route("/api/connect", methods=["POST"])
        def connect():
            """连接交易服务器"""
            try:
                data = request.json

                # 更新配置
                if data:
                    self.config_manager.update_ctp_config(data, save=True)

                # 获取 CTP 配置
                ctp_config = self.config_manager.get_ctp_config()

                # 连接
                self.main_engine.connect(ctp_config, "CTP")

                self._add_log("INFO", "正在连接交易服务器...")

                # 延迟自动订阅（等待连接成功）
                import threading

                def delayed_subscribe():
                    import time

                    time.sleep(8)  # 等待8秒让连接完成
                    self.auto_subscribe_saved_symbols()

                threading.Thread(target=delayed_subscribe, daemon=True).start()

                return jsonify({"success": True, "message": "连接请求已发送"})
            except Exception as e:
                logger.error(f"连接失败: {e}")
                return jsonify({"success": False, "message": str(e)}), 500

        @self.flask_app.route("/api/subscriptions", methods=["GET", "DELETE"])
        def manage_subscriptions():
            """管理订阅列表"""
            if request.method == "GET":
                # 获取订阅列表
                subscriptions = self.config_manager.get_subscriptions()
                return jsonify({"success": True, "data": subscriptions})

            elif request.method == "DELETE":
                # 删除订阅
                data = request.json
                symbol = data.get("symbol")
                exchange = data.get("exchange")

                if not symbol or not exchange:
                    return jsonify({"success": False, "message": "参数不完整"}), 400

                self.config_manager.remove_subscription(symbol, exchange)

                # 从当前订阅集合中移除
                vt_symbol = f"{symbol}.{exchange}"
                self.subscribed_symbols.discard(vt_symbol)

                return jsonify({"success": True, "message": f"已删除订阅 {vt_symbol}"})

        @self.flask_app.route("/api/disconnect", methods=["POST"])
        def disconnect():
            """断开连接"""
            try:
                self.main_engine.close()
                self.connection_status["connected"] = False
                self.connection_status["td_connected"] = False
                self.connection_status["md_connected"] = False
                self._emit_connection_status()

                self._add_log("INFO", "已断开连接")

                return jsonify({"success": True, "message": "已断开连接"})
            except Exception as e:
                logger.error(f"断开连接失败: {e}")
                return jsonify({"success": False, "message": str(e)}), 500

        @self.flask_app.route("/api/contract_info/<symbol>", methods=["GET"])
        def get_contract_info(symbol):
            """获取合约信息"""
            try:
                contract = self.contracts.get(symbol)
                if not contract:
                    return jsonify({"success": False, "message": "合约信息不存在"}), 404

                return jsonify(
                    {
                        "success": True,
                        "data": {
                            "symbol": contract.symbol,
                            "exchange": contract.exchange.value,
                            "name": contract.name,
                            "size": contract.size,
                            "pricetick": contract.pricetick,
                            "min_volume": contract.min_volume,
                            "product": contract.product.value
                            if contract.product
                            else "",
                        },
                    }
                )
            except Exception as e:
                logger.error(f"获取合约信息失败: {e}")
                return jsonify({"success": False, "message": str(e)}), 500

        @self.flask_app.route("/api/subscribe", methods=["POST"])
        def subscribe():
            """订阅行情"""
            try:
                data = request.json
                symbol = data.get("symbol")
                exchange_str = data.get("exchange", "SHFE")

                if not symbol:
                    return jsonify(
                        {"success": False, "message": "合约代码不能为空"}
                    ), 400

                # 解析交易所
                try:
                    exchange = Exchange(exchange_str)
                except ValueError:
                    exchange = Exchange.SHFE

                # 创建订阅请求
                req = SubscribeRequest(symbol=symbol, exchange=exchange)
                self.main_engine.subscribe(req, "CTP")

                vt_symbol = f"{symbol}.{exchange.value}"
                self.subscribed_symbols.add(vt_symbol)

                # 保存订阅到配置
                self.config_manager.add_subscription(symbol, exchange_str)

                self._add_log("INFO", f"已订阅并保存 {vt_symbol}")

                return jsonify(
                    {"success": True, "message": f"已订阅 {vt_symbol}（已保存）"}
                )
            except Exception as e:
                logger.error(f"订阅失败: {e}")
                return jsonify({"success": False, "message": str(e)}), 500

        @self.flask_app.route("/api/send_order", methods=["POST"])
        def send_order():
            """发送订单"""
            try:
                data = request.json

                # 检查交易是否允许
                allowed, reason = self.risk_manager.is_trading_allowed()
                if not allowed:
                    return jsonify(
                        {"success": False, "message": f"交易已暂停: {reason}"}
                    ), 403

                # 解析参数
                symbol = data.get("symbol")
                exchange_str = data.get("exchange", "SHFE")
                direction_str = data.get("direction")
                offset_str = data.get("offset")
                price = float(data.get("price"))
                volume = float(data.get("volume"))

                # 校验参数
                if not all([symbol, direction_str, offset_str, price, volume]):
                    return jsonify({"success": False, "message": "参数不完整"}), 400

                # 转换为枚举
                try:
                    exchange = Exchange(exchange_str)

                    # Direction 映射 - 支持字符串和枚举名
                    if direction_str == "LONG" or direction_str == "多":
                        direction = Direction.LONG
                    elif direction_str == "SHORT" or direction_str == "空":
                        direction = Direction.SHORT
                    else:
                        direction = Direction(direction_str)

                    # Offset 映射 - 支持字符串和枚举名
                    if offset_str == "OPEN" or offset_str == "开":
                        offset = Offset.OPEN
                    elif offset_str == "CLOSE" or offset_str == "平":
                        offset = Offset.CLOSE
                    elif offset_str == "CLOSETODAY" or offset_str == "平今":
                        offset = Offset.CLOSETODAY
                    elif offset_str == "CLOSEYESTERDAY" or offset_str == "平昨":
                        offset = Offset.CLOSEYESTERDAY
                    else:
                        offset = Offset(offset_str)

                except (ValueError, AttributeError) as e:
                    return jsonify({"success": False, "message": f"参数错误: {e}"}), 400

                vt_symbol = f"{symbol}.{exchange.value}"
                account = list(self.accounts.keys())[0] if self.accounts else "default"

                # 风控检查
                # 1. 合约代码合法性
                valid, msg = self.risk_manager.validate_contract(vt_symbol)
                if not valid:
                    return jsonify({"success": False, "message": msg}), 400

                # 2. 价格最小变动价位
                valid, msg = self.risk_manager.validate_price(vt_symbol, price)
                if not valid:
                    return jsonify(
                        {"success": False, "message": f"价格验证失败: {msg}"}
                    ), 400

                # 3. 单笔最大手数
                valid, msg = self.risk_manager.validate_volume(volume)
                if not valid:
                    return jsonify({"success": False, "message": msg}), 400

                # 4. 市场状态
                valid, msg = self.risk_manager.validate_market_status(vt_symbol)
                if not valid:
                    return jsonify({"success": False, "message": msg}), 400

                # 5. 重复报单检查
                if offset == Offset.OPEN:
                    passed, alert = self.risk_manager.check_repeat_open(
                        account, vt_symbol
                    )
                else:
                    passed, alert = self.risk_manager.check_repeat_close(
                        account, vt_symbol
                    )

                # 6. 报单总量检查
                self.risk_manager.check_total_orders(account)

                # 创建订单请求
                req = OrderRequest(
                    symbol=symbol,
                    exchange=exchange,
                    direction=direction,
                    type=OrderType.LIMIT,
                    volume=volume,
                    price=price,
                    offset=offset,
                    reference="WebUI",
                )

                # 发送订单
                vt_orderid = self.main_engine.send_order(req, "CTP")

                with self.data_lock:
                    self.trade_statistics["total_orders"] += 1

                self._add_log("INFO", f"订单已发送: {vt_orderid}")

                return jsonify(
                    {"success": True, "message": "订单已发送", "vt_orderid": vt_orderid}
                )
            except Exception as e:
                logger.error(f"发送订单失败: {e}")
                return jsonify({"success": False, "message": str(e)}), 500

        @self.flask_app.route("/api/cancel_order", methods=["POST"])
        def cancel_order():
            """撤单"""
            try:
                data = request.json
                vt_orderid = data.get("vt_orderid")

                if not vt_orderid:
                    return jsonify({"success": False, "message": "订单ID不能为空"}), 400

                # 获取订单
                order = self.orders.get(vt_orderid)
                if not order:
                    return jsonify({"success": False, "message": "订单不存在"}), 404

                # 风控检查 - 重复撤单
                account = list(self.accounts.keys())[0] if self.accounts else "default"
                self.risk_manager.check_repeat_cancel(account, order.vt_symbol)
                self.risk_manager.check_total_cancels(account)

                # 创建撤单请求
                req = CancelRequest(
                    orderid=order.orderid, symbol=order.symbol, exchange=order.exchange
                )

                # 发送撤单
                self.main_engine.cancel_order(req, "CTP")

                self._add_log("INFO", f"撤单请求已发送: {vt_orderid}")

                return jsonify({"success": True, "message": "撤单请求已发送"})
            except Exception as e:
                logger.error(f"撤单失败: {e}")
                return jsonify({"success": False, "message": str(e)}), 500

        @self.flask_app.route("/api/partial_cancel", methods=["POST"])
        def partial_cancel():
            """部分撤单（撤销原订单并重新下单保留指定数量）"""
            try:
                data = request.json
                vt_orderid = data.get("vt_orderid")
                keep_volume = float(data.get("keep_volume", 0))

                if not vt_orderid:
                    return jsonify({"success": False, "message": "订单ID不能为空"}), 400

                if keep_volume <= 0:
                    return jsonify(
                        {"success": False, "message": "保留数量必须大于0"}
                    ), 400

                # 获取订单
                order = self.orders.get(vt_orderid)
                if not order:
                    return jsonify({"success": False, "message": "订单不存在"}), 404

                # 检查订单状态
                if not order.is_active():
                    return jsonify(
                        {
                            "success": False,
                            "message": "订单已完成或已撤销，无法部分撤单",
                        }
                    ), 400

                # 计算未成交数量
                remaining_volume = order.volume - order.traded

                if remaining_volume <= 0:
                    return jsonify(
                        {"success": False, "message": "订单已全部成交，无需撤单"}
                    ), 400

                if keep_volume >= remaining_volume:
                    return jsonify(
                        {
                            "success": False,
                            "message": f"保留数量({keep_volume})必须小于未成交数量({remaining_volume})",
                        }
                    ), 400

                # 风控检查
                account = list(self.accounts.keys())[0] if self.accounts else "default"
                self.risk_manager.check_repeat_cancel(account, order.vt_symbol)

                # 1. 撤销原订单
                cancel_req = CancelRequest(
                    orderid=order.orderid, symbol=order.symbol, exchange=order.exchange
                )
                self.main_engine.cancel_order(cancel_req, "CTP")

                # 2. 重新下保留数量的订单
                new_order_req = OrderRequest(
                    symbol=order.symbol,
                    exchange=order.exchange,
                    direction=order.direction,
                    type=order.type,
                    volume=keep_volume,
                    price=order.price,
                    offset=order.offset,
                    reference="WebUI_PartialCancel",
                )

                new_vt_orderid = self.main_engine.send_order(new_order_req, "CTP")

                cancel_volume = remaining_volume - keep_volume
                message = f"部分撤单成功: 撤销 {cancel_volume} 手，保留 {keep_volume} 手，新订单号: {new_vt_orderid}"
                self._add_log("INFO", message)

                return jsonify(
                    {
                        "success": True,
                        "message": message,
                        "new_vt_orderid": new_vt_orderid,
                        "cancelled_volume": cancel_volume,
                        "keep_volume": keep_volume,
                    }
                )

            except Exception as e:
                logger.error(f"部分撤单失败: {e}")
                return jsonify(
                    {"success": False, "message": f"部分撤单失败: {str(e)}"}
                ), 500

        @self.flask_app.route("/api/cancel_all", methods=["POST"])
        def cancel_all():
            """全部撤单"""
            try:
                # 获取所有活动订单（未成交或部分成交）
                active_orders = [
                    order for order in self.orders.values() if order.is_active()
                ]

                if not active_orders:
                    return jsonify(
                        {"success": True, "message": "当前没有未成交的订单需要撤销"}
                    )

                count = 0
                failed = 0
                for order in active_orders:
                    try:
                        req = CancelRequest(
                            orderid=order.orderid,
                            symbol=order.symbol,
                            exchange=order.exchange,
                        )
                        self.main_engine.cancel_order(req, "CTP")
                        count += 1
                    except Exception as e:
                        logger.error(f"撤单失败 {order.vt_orderid}: {e}")
                        failed += 1

                msg = f"批量撤单完成: 成功 {count} 笔"
                if failed > 0:
                    msg += f", 失败 {failed} 笔"

                self._add_log("INFO", msg)

                return jsonify({"success": True, "message": msg})
            except Exception as e:
                logger.error(f"批量撤单失败: {e}")
                return jsonify({"success": False, "message": str(e)}), 500

        @self.flask_app.route("/api/pause_trading", methods=["POST"])
        def pause_trading():
            """暂停交易"""
            try:
                data = request.json
                reason = data.get("reason", "手动暂停")

                self.risk_manager.pause_trading(reason)

                return jsonify({"success": True, "message": "交易已暂停"})
            except Exception as e:
                logger.error(f"暂停交易失败: {e}")
                return jsonify({"success": False, "message": str(e)}), 500

        @self.flask_app.route("/api/resume_trading", methods=["POST"])
        def resume_trading():
            """恢复交易"""
            try:
                self.risk_manager.resume_trading()

                return jsonify({"success": True, "message": "交易已恢复"})
            except Exception as e:
                logger.error(f"恢复交易失败: {e}")
                return jsonify({"success": False, "message": str(e)}), 500

        @self.flask_app.route("/api/data/ticks")
        def get_ticks():
            """获取 Tick 数据"""
            with self.data_lock:
                ticks_data = [
                    {
                        "symbol": tick.vt_symbol,
                        "last_price": tick.last_price,
                        "volume": tick.volume,
                        "datetime": tick.datetime.strftime("%Y-%m-%d %H:%M:%S")
                        if tick.datetime
                        else "",
                    }
                    for tick in self.ticks.values()
                ]
            return jsonify({"success": True, "data": ticks_data})

        @self.flask_app.route("/api/data/orders")
        def get_orders():
            """获取订单数据"""
            with self.data_lock:
                orders_data = [
                    {
                        "vt_orderid": order.vt_orderid,
                        "symbol": order.vt_symbol,
                        "direction": order.direction.value,
                        "offset": order.offset.value,
                        "price": order.price,
                        "volume": order.volume,
                        "traded": order.traded,
                        "status": order.status.name,  # 使用枚举名而不是中文值
                        "datetime": order.datetime.strftime("%Y-%m-%d %H:%M:%S")
                        if order.datetime
                        else "",
                    }
                    for order in self.orders.values()
                ]
            return jsonify({"success": True, "data": orders_data})

        @self.flask_app.route("/api/data/trades")
        def get_trades():
            """获取成交数据"""
            with self.data_lock:
                trades_data = [
                    {
                        "vt_tradeid": trade.vt_tradeid,
                        "symbol": trade.vt_symbol,
                        "direction": trade.direction.value,
                        "offset": trade.offset.value,
                        "price": trade.price,
                        "volume": trade.volume,
                        "datetime": trade.datetime.strftime("%Y-%m-%d %H:%M:%S")
                        if trade.datetime
                        else "",
                    }
                    for trade in self.trades.values()
                ]
            return jsonify({"success": True, "data": trades_data})

        @self.flask_app.route("/api/data/positions")
        def get_positions():
            """获取持仓数据"""
            with self.data_lock:
                positions_data = [
                    {
                        "vt_positionid": pos.vt_positionid,
                        "symbol": pos.vt_symbol,
                        "direction": pos.direction.name,  # 使用枚举名而不是中文值
                        "volume": pos.volume,
                        "frozen": pos.frozen,
                        "price": pos.price,
                        "pnl": pos.pnl,
                    }
                    for pos in self.positions.values()
                ]
            return jsonify({"success": True, "data": positions_data})

        @self.flask_app.route("/api/data/accounts")
        def get_accounts():
            """获取账户数据"""
            with self.data_lock:
                accounts_data = [
                    {
                        "vt_accountid": acc.vt_accountid,
                        "balance": acc.balance,
                        "frozen": acc.frozen,
                        "available": acc.available,
                    }
                    for acc in self.accounts.values()
                ]
            return jsonify({"success": True, "data": accounts_data})

        @self.flask_app.route("/api/data/contracts")
        def get_contracts():
            """获取合约数据"""
            with self.data_lock:
                contracts_data = [
                    {
                        "vt_symbol": contract.vt_symbol,
                        "name": contract.name,
                        "exchange": contract.exchange.value,
                        "size": contract.size,
                        "pricetick": contract.pricetick,
                        "product": contract.product.value if contract.product else "",
                    }
                    for contract in self.contracts.values()
                ]
            return jsonify({"success": True, "data": contracts_data})

        @self.flask_app.route("/api/logs")
        def get_logs():
            """获取日志"""
            limit = request.args.get("limit", 100, type=int)
            with self.data_lock:
                logs_data = self.logs[-limit:]
            return jsonify({"success": True, "data": list(reversed(logs_data))})

        @self.flask_app.route("/api/alerts")
        def get_alerts():
            """获取告警"""
            limit = request.args.get("limit", 100, type=int)
            alerts = self.risk_manager.get_alerts(limit=limit)
            alerts_data = [
                {
                    "alert_id": alert.alert_id,
                    "type": alert.alert_type.value,
                    "level": alert.level.value,
                    "message": alert.message,
                    "timestamp": alert.timestamp.strftime("%Y-%m-%d %H:%M:%S"),
                    "account": alert.account,
                    "symbol": alert.symbol,
                }
                for alert in alerts
            ]
            return jsonify({"success": True, "data": alerts_data})

        @self.flask_app.route("/api/config", methods=["GET", "POST"])
        def manage_config():
            """管理配置"""
            if request.method == "GET":
                # 获取配置
                config_type = request.args.get("type", "all")
                if config_type == "risk":
                    config_data = self.config_manager.get_risk_config()
                elif config_type == "validation":
                    config_data = self.config_manager.get_validation_config()
                elif config_type == "alert":
                    config_data = self.config_manager.get_alert_config()
                elif config_type == "ctp":
                    config_data = self.config_manager.get("ctp", {})
                    # 隐藏密码
                    if "password" in config_data:
                        config_data["password"] = "****"
                else:
                    config_data = self.config_manager.get_all_config()

                return jsonify({"success": True, "data": config_data})

            elif request.method == "POST":
                # 更新配置
                data = request.json
                config_type = data.get("type")
                config_value = data.get("value", {})

                if config_type == "risk":
                    success = self.config_manager.update_risk_config(config_value)
                    if success:
                        # 更新风控管理器
                        new_config = ThresholdConfig(
                            **self.config_manager.get_risk_config()
                        )
                        self.risk_manager.update_config(new_config)
                elif config_type == "validation":
                    success = self.config_manager.update_validation_config(config_value)
                    if success:
                        new_rule = ValidationRule(
                            **self.config_manager.get_validation_config()
                        )
                        self.risk_manager.update_validation_rule(new_rule)
                elif config_type == "alert":
                    success = self.config_manager.update_alert_config(config_value)
                else:
                    success = False

                if success:
                    return jsonify({"success": True, "message": "配置已更新"})
                else:
                    return jsonify({"success": False, "message": "配置更新失败"}), 500

    def _register_socketio_events(self):
        """注册 SocketIO 事件"""

        @self.socketio.on("connect")
        def handle_connect():
            """客户端连接"""
            logger.info("客户端已连接")
            emit("connection_status", self.connection_status)

        @self.socketio.on("disconnect")
        def handle_disconnect():
            """客户端断开"""
            logger.info("客户端已断开")

    def run(self, host=None, port=None, debug=False):
        """启动应用"""
        # 从配置读取
        webui_config = self.config_manager.get_webui_config()
        host = host or webui_config.get("host", "0.0.0.0")
        port = port or webui_config.get("port", 8080)
        debug = debug or webui_config.get("debug", False)

        logger.info(f"启动 WebUI 服务: http://{host}:{port}")

        # 启动 SocketIO 服务器
        self.socketio.run(
            self.flask_app,
            host=host,
            port=port,
            debug=debug,
            allow_unsafe_werkzeug=True,
        )


def main():
    """主函数"""
    # 确保日志目录存在
    # Path("logs").mkdir(exist_ok=True) # 已经在全局配置中处理

    # 创建应用
    app = TradingWebUIApp("config.json")

    # 启动应用
    app.run()


if __name__ == "__main__":
    main()
