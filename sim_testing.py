#!/usr/bin/env python3
import sys
from copy import deepcopy
import setting
from types import MethodType
from time import sleep
import pandas as pd
from datetime import datetime, timedelta
from vnpy.event import EventEngine, Event
from vnpy.trader.engine import MainEngine
from vnpy.trader.object import SubscribeRequest, HistoryRequest, ContractData, TickData
from vnpy.trader.constant import Exchange, Interval
from vnpy.trader.event import EVENT_CONTRACT, EVENT_TICK
from vnpy_ctp import CtpGateway
from vnpy_ctastrategy import CtaEngine, CtaStrategyApp
from vnpy_ctastrategy.backtesting import BacktestingEngine
from vnpy.trader.datafeed import get_datafeed
from vnpy.trader.database import get_database
import time
from pathlib import Path
import logging
import os
import select
from datetime import time as dt_time
from utils.logger import RunLogger, RecordEngine
from strategies.silver_t_CTP import SilverT


sys.path.append(os.path.abspath(os.path.join(os.getcwd())))


# 回测标的与级别
symbol = "ag2512"  # 沪银主连合约
level = Interval.MINUTE  # K线级别
strategy_name = "silver_t_CTP"


# 日志配置
logger = RunLogger(
    run_prefix="live_ctp",
    rotate="time",
    db_dsn=os.getenv("PG_DSN"),
    db_init_schema=True,
    run_params={"strategy": "silver_t", "symbols": [symbol]},
    tags=["prod", "ctp", "simnow"],
)
# logger.bind_write_log(SilverT, "SilverT")  # 绑定日志写入方法


# 回测参数（可调整）
BACKTEST_PARAMS = {
    "vt_symbol": symbol + ".SHFE",
    "interval": level,
    "start": datetime.now() - timedelta(days=21),
    "end": datetime.now(),
    "rate": 0.3 / 10000,  # 手续费率
    "slippage": 1,  # 滑点
    "size": 10,  # 沪银合约乘数（标准10手）
    "pricetick": 1,  # 最小价格变动
    "capital": 3000000,  # 初始资金
}


def get_history_data():
    """获取历史数据"""
    db = get_database()
    datafeed = get_datafeed()
    req = HistoryRequest(
        symbol=symbol,
        exchange=Exchange.SHFE,
        start=BACKTEST_PARAMS["start"],
        end=BACKTEST_PARAMS["end"],
        interval=level,
    )
    bars = datafeed.query_bar_history(req)
    db.save_bar_data(bars)
    bars_from_db = db.load_bar_data(
        symbol=req.symbol,
        exchange=req.exchange,
        interval=req.interval,
        start=req.start,
        end=req.end,
    )
    return bars_from_db


def run_backtest():
    """使用历史数据运行回测，计算统计，并记录交易日志"""

    # 初始化数据库
    db = get_database()

    # 配置 datafeed 数据源
    datafeed = get_datafeed()
    req = HistoryRequest(
        symbol=symbol,
        exchange=Exchange.SHFE,
        start=BACKTEST_PARAMS["start"],
        end=BACKTEST_PARAMS["end"],
        interval=level,
    )

    bars = datafeed.query_bar_history(req)
    db.save_bar_data(bars)
    bars_from_db = db.load_bar_data(
        symbol=req.symbol,
        exchange=req.exchange,
        interval=req.interval,
        start=req.start,
        end=req.end,
    )

    logging.info(f"回测数据加载完成：{len(bars)} 条 Bar")

    # 初始化回测引擎
    backtesting_engine = BacktestingEngine()
    backtesting_engine.history_data = bars_from_db

    # 设置参数
    backtesting_engine.set_parameters(
        vt_symbol=BACKTEST_PARAMS["vt_symbol"],
        interval=BACKTEST_PARAMS["interval"],
        start=BACKTEST_PARAMS["start"],
        end=BACKTEST_PARAMS["end"],
        rate=BACKTEST_PARAMS["rate"],
        slippage=BACKTEST_PARAMS["slippage"],
        size=BACKTEST_PARAMS["size"],
        pricetick=BACKTEST_PARAMS["pricetick"],
        capital=BACKTEST_PARAMS["capital"],
    )

    # 添加策略
    backtesting_engine.add_strategy(
        SilverT, {"account_equity": BACKTEST_PARAMS["capital"]}
    )
    backtesting_engine.logger = logger

    # 直接加载 Bar 数据进行回测
    backtesting_engine.load_data()

    # 运行回测
    backtesting_engine.run_backtesting()

    backtesting_engine.logger = None
    strategy = deepcopy(backtesting_engine.strategy)
    strategy.logger = logger
    strategy.strategy_name = strategy_name

    # 计算统计
    backtesting_engine.calculate_result()
    backtesting_engine.calculate_statistics()

    return strategy


def is_trading_time(now: datetime = None) -> bool:
    """判断当前是否在交易时间内（沪银期货交易时间）

    交易时间段：
    - 上午：09:00 - 11:30
    - 下午：13:30 - 15:00
    - 夜盘：21:00 - 02:30（次日）
    """
    if now is None:
        now = datetime.now()

    current_time = now.time()

    # 上午交易时间：09:00 - 11:30
    if dt_time(9, 0) <= current_time <= dt_time(11, 30):
        return True

    # 下午交易时间：13:30 - 15:00
    if dt_time(13, 30) <= current_time <= dt_time(15, 0):
        return True

    # 夜盘交易时间：21:00 - 02:30（次日）
    if current_time >= dt_time(21, 0) or current_time <= dt_time(2, 30):
        return True

    return False


def main():
    event_engine = EventEngine()

    main_engine = MainEngine(event_engine)
    main_engine.add_gateway(CtpGateway)
    main_engine.add_app(CtaStrategyApp)

    main_engine.add_engine(RecordEngine)
    main_engine.get_engine("recorder").logger = logger

    # 第一步：读取历史数据，进行回测
    # strategy = run_backtest()

    # 用于跟踪合约是否已加载
    target_vt_symbol = f"{symbol}.{Exchange.SHFE.value}"
    contract_loaded = {"status": False}
    subscribed = {"status": False}
    tick_count = {"count": 0}

    # 定义合约推送处理函数
    def on_contract(event: Event) -> None:
        """处理合约推送事件"""
        contract: ContractData = event.data
        if contract.vt_symbol == target_vt_symbol:
            contract_loaded["status"] = True
            logger.info(f"合约 {contract.vt_symbol} 已加载: {contract.name}")

            # 合约加载后立即订阅行情
            if not subscribed["status"]:
                req = SubscribeRequest(
                    symbol=contract.symbol, exchange=contract.exchange
                )
                main_engine.subscribe(req, "CTP")
                subscribed["status"] = True
                logger.info(f"已订阅 {contract.vt_symbol} 的实时行情")

    # 定义 Tick 事件处理函数（用于调试）
    def on_tick(event: Event) -> None:
        """处理 Tick 推送事件"""
        tick: TickData = event.data
        if tick.vt_symbol == target_vt_symbol:
            tick_count["count"] += 1
            # 每收到10个tick打印一次，避免日志过多
            if tick_count["count"] % 10 == 1:
                logger.info(
                    f"收到 Tick #{tick_count['count']}: {tick.datetime} - {tick.last_price}"
                )

    # 注册事件监听
    event_engine.register(EVENT_CONTRACT, on_contract)
    event_engine.register(EVENT_TICK, on_tick)

    # 第二步：添加CTP Gateway，连接SimNow模拟盘
    SIMNOW_CONFIG = {
        "交易服务器": os.getenv("SIMNOW_TRADE_SERVER", "your_simnow_trade_server"),
        "行情服务器": os.getenv("SIMNOW_MARKET_SERVER", "your_simnow_market_server"),
        "经纪商代码": os.getenv("SIMNOW_BROKER_ID", "your_simnow_broker_id"),
        "用户名": os.getenv("SIMNOW_USERID", "your_simnow_userid"),
        "密码": os.getenv("SIMNOW_PASSWORD", "your_simnow_password"),
        "产品名称": os.getenv("SIMNOW_APPID", "your_simnow_appid"),
        "授权编码": os.getenv("SIMNOW_AUTHCODE", "your_simnow_authcode"),
        "柜台环境": ["实盘", "测试"][1],  # 选择测试环境
    }
    main_engine.connect(SIMNOW_CONFIG, "CTP")
    logger.info("正在连接 CTP 接口，请等待...")

    # 第三步：等待连接和登录完成（CTP 需要时间完成连接、登录和合约信息推送）
    sleep(5)
    logger.info("CTP 连接初始化完成，等待合约信息推送...")

    # 等待合约信息推送（最多等待30秒）
    max_wait_time = 30
    waited_time = 0
    while not contract_loaded["status"] and waited_time < max_wait_time:
        sleep(1)
        waited_time += 1
        if waited_time % 5 == 0:
            logger.info(f"等待合约信息推送... ({waited_time}/{max_wait_time}秒)")

    if not contract_loaded["status"]:
        logger.warning(
            f"等待 {max_wait_time} 秒后仍未收到合约 {target_vt_symbol} 的信息，尝试直接订阅..."
        )
        # 如果等待超时，尝试直接订阅
        req = SubscribeRequest(symbol=symbol, exchange=Exchange.SHFE)
        main_engine.subscribe(req, "CTP")
        subscribed["status"] = True
    else:
        logger.info("合约信息已加载，订阅请求已发送")

    # 第四步：初始化 CTA 引擎
    cta_engine = CtaEngine(main_engine, event_engine)
    cta_engine.init_engine()
    cta_engine.write_log = MethodType(
        lambda self, msg, strategy=None: logger.info(
            f"{strategy.strategy_name if strategy else 'CTA Engine'}: {msg}"
        ),
        cta_engine,
    )

    # 第五步：添加并启动策略
    cta_engine.load_strategy_class_from_module(f"strategies.{strategy_name}")

    cta_engine.add_strategy("SilverT", strategy_name, BACKTEST_PARAMS["vt_symbol"], {})
    cta_engine.init_strategy(strategy_name)

    # 兼容性：strategy key 可能与期望不同，做健壮处理
    try:
        cta_engine.strategies[strategy_name].logger = logger
    except KeyError:
        # 尝试按 class name 或策略对象内的 strategy_name 属性寻找匹配项
        found_key = None
        for k, v in cta_engine.strategies.items():
            try:
                if v.__class__.__name__ == "SilverT":
                    found_key = k
                    break
                if getattr(v, "strategy_name", None) == strategy_name:
                    found_key = k
                    break
            except Exception:
                continue

        if found_key:
            logger.info(f"策略键 {strategy_name} 未找到，使用匹配到的键 {found_key}")
            cta_engine.strategies[found_key].logger = logger
        else:
            logger.warning(
                f"未能在 cta_engine.strategies 中找到策略 {strategy_name}，当前 keys={list(cta_engine.strategies.keys())}"
            )

    time.sleep(5)
    cta_engine.start_strategy(strategy_name)

    # 第六步：预热策略
    bars = get_history_data()
    strategy = cta_engine.strategies[strategy_name]
    for bar in bars:
        strategy.on_bar(bar)
    logger.info(f"策略预热完成，已加载 {len(bars)} 条行情数据")

    # 第七步：确保订阅已发送
    if not subscribed["status"]:
        req = SubscribeRequest(symbol=symbol, exchange=Exchange.SHFE)
        main_engine.subscribe(req, "CTP")
        subscribed["status"] = True
        logger.info(f"手动订阅 {target_vt_symbol} 的实时行情")

    logger.info("SimNow模拟盘订阅启动，按 Ctrl+C 停止...")

    # 为了兼容 Windows 控制台（msvcrt），在 Windows 下使用 msvcrt 非阻塞读取键盘。
    input_buffer = ""
    use_msvcrt = os.name == "nt"
    msvcrt = None
    if use_msvcrt:
        try:
            import msvcrt as _msvcrt  # type: ignore

            msvcrt = _msvcrt
        except Exception:
            use_msvcrt = False

    # 辅助：非阻塞检查是否有退出指令，返回 True 表示应退出
    def check_exit_now():
        nonlocal input_buffer
        if use_msvcrt and msvcrt is not None:
            try:
                while msvcrt.kbhit():
                    ch = msvcrt.getwch()
                    # 处理回车：完成一行输入
                    if ch in ("\r", "\n"):
                        line = input_buffer
                        input_buffer = ""
                        if line.strip().lower() == "exit":
                            logger.info("收到退出指令，停止策略...")
                            return True
                    # Ctrl-C
                    elif ch == "\x03":
                        raise KeyboardInterrupt
                    # 退格
                    elif ch == "\x08":
                        input_buffer = input_buffer[:-1]
                    # 单键退出（方便快速中断）
                    elif ch.lower() in ("q", "x"):
                        logger.info("收到单键退出指令，停止策略...")
                        return True
                    else:
                        input_buffer += ch
            except KeyboardInterrupt:
                raise
            except Exception:
                return False
            return False
        else:
            try:
                rlist, _, _ = select.select([sys.stdin], [], [], 0)
                if rlist:
                    line = sys.stdin.readline()
                    if line.strip().lower() == "exit":
                        logger.info("收到退出指令，停止策略...")
                        return True
            except Exception:
                return False
            return False

    try:
        while True:
            if is_trading_time():
                # 交易时间内，短暂睡眠以监听Tick
                time.sleep(1)

                # 检查退出指令
                if check_exit_now():
                    break
            else:
                # 休盘时间：不要一次睡太久，分段睡眠并检查退出，保证能够及时响应
                logger.info("当前为休盘时间，进入轮询休眠（可按 exit 或按键退出）...")
                # 分段睡眠 1 秒，累计到 300 秒后退出本次长眠
                sleep_seconds = 300
                slept = 0
                while slept < sleep_seconds:
                    time.sleep(1)
                    slept += 1
                    if check_exit_now():
                        raise KeyboardInterrupt

    except KeyboardInterrupt:
        logger.info("终端中断或收到退出指令，准备停止策略...")
    finally:
        # 确保一定会执行清理
        try:
            cta_engine.stop_strategy(strategy_name)
        except Exception:
            pass
        try:
            main_engine.close()
        except Exception:
            pass
        # 尝试正常退出，若仍有后台线程阻止退出则强制终止进程
        try:
            logger.info("执行退出清理完成，尝试正常退出程序...")
            sys.exit(0)
        except SystemExit:
            # 如果 Python 解释器未退出（存在非守护线程），使用强制退出
            logger.info("正常退出失败，使用强制退出 os._exit(0)")
            try:
                os._exit(0)
            except Exception:
                pass


if __name__ == "__main__":
    main()
