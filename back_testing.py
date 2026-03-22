from vnpy_ctastrategy.strategies.atr_rsi_strategy import AtrRsiStrategy
from vnpy_ctastrategy.strategies.double_ma_strategy import DoubleMaStrategy
from vnpy_ctastrategy.backtesting import BacktestingEngine
from vnpy.trader.datafeed import get_datafeed
from vnpy.trader.constant import Interval
from datetime import datetime
import pickle
import json
import logging
import time
import pandas as pd

import plotly.io as pio

# Notebook 添加路径
import sys
import os

from vnpy.trader.setting import SETTINGS  # safe to import early

if not SETTINGS.get("database.timezone"):
    SETTINGS["database.timezone"] = "Asia/Shanghai"

# sys.path.append(os.path.abspath(os.path.join(os.getcwd(), "..")))

from vnpy_ctastrategy.strategies.atr_rsi_strategy import AtrRsiStrategy
from vnpy_ctastrategy.strategies.double_ma_strategy import DoubleMaStrategy
from vnpy_ctastrategy.backtesting import BacktestingEngine
from vnpy.trader.datafeed import get_datafeed
from vnpy.trader.constant import Interval
from datetime import datetime
import pickle

# from strategies.pxc_test_strategy import SilverT
from strategies.silver_t import SilverT
# from strategies.silver_t_biao import SilverT
from utils.logger import RunLogger

# Parameter settings
capital = 3000000

# 重新创建回测引擎
enging = BacktestingEngine()

# 设置回测参数
# enging.set_parameters(
#     vt_symbol="ag2512.SHFE",
#     interval="1m",
#     start=datetime(2025, 1, 1),
#     end=datetime(2025, 9, 14),
#     rate=0.3 / 10000,
#     slippage=1,
#     size=10,
#     pricetick=1,
#     capital=capital,
# )
# enging.set_parameters(
#     vt_symbol="ag2510.SHFE",
#     interval="1m",
#     start=datetime(2025, 7, 15),
#     end=datetime(2025, 9, 12),
#     rate=0.3 / 10000,
#     slippage=1,
#     size=10,
#     pricetick=1,
#     capital=capital,
# )
# enging.set_parameters(
#     vt_symbol="ag2512.SHFE",
#     interval="1m",
#     start=datetime(2025, 9, 1),
#     end=datetime(2025, 10, 27),
#     rate=0.3 / 10000,
#     slippage=1,
#     size=10,
#     pricetick=1,
#     capital=capital,
# )

enging.set_parameters(
    vt_symbol="ag9999.SHFE",
    interval="1m",
    start=datetime(2025, 1, 1),
    end=datetime(2025, 10, 27),
    rate=0.3 / 10000,
    slippage=1,
    size=10,
    pricetick=1,
    capital=capital,
)

# 加载数据
# with open("data/ag2512_1m_250901_251027.pkl", "rb") as f:
#     enging.history_data = pickle.load(f)

# with open("data/ag2510_1m_250715_250912.pkl", "rb") as f:
#     enging.history_data = pickle.load(f)

with open("data/白银主连数据/2025年/分钟级/ag88_1m_250101_251027.pkl", "rb") as f:
    enging.history_data = pickle.load(f)

# enging.set_parameters(
#     vt_symbol="jm2601.DCE",
#     interval="1m",
#     start=datetime(2025, 7, 1),
#     end=datetime(2025, 8, 1),
#     rate=0.3 / 10000,
#     slippage=1,
#     size=10,
#     pricetick=1,
#     capital=1000000,
# )
# # 加载数据
# with open("data/jm2601_1m.pkl", "rb") as f:
#     enging.history_data = pickle.load(f)


# log = RunLogger(
#     log_root="logs",
#     run_prefix="back_testing",
#     console=True,
#     rotate="time",
# )

logger = RunLogger(
    run_prefix="back_testing",
    rotate="time",
    db_dsn=os.getenv("PG_DSN"),
    db_init_schema=False,
    run_params={"strategy": "silver_t", "symbols": ["ag9999"]},
    tags=["backtest"],
)

# logger.bind_write_log(SilverT, "白银做 T 策略")
# SilverT.write_log = lambda self, msg: logger.info(msg)

# 添加策略
# enging.add_strategy(AtrRsiStrategy, {})
# enging.add_strategy(DoubleMaStrategy, {})
# enging.add_strategy(ChannelTrendATRStrategy, {})
enging.add_strategy(
    SilverT,
    {
        "account_equity": capital,
        "logger": logger,
        "tp_points": 180,
        "sl_points": 60,
    },
)

enging.strategy.logger = logger

# 运行回测
enging.run_backtesting()

# 显示回测结果
enging.output = lambda x: print(x)  # 不格式化输出

# Save strategy parameters to json
strategy = enging.strategy
params = strategy.get_parameters()

# Save results to a CSV file
enging.calculate_result()
enging.calculate_statistics()
# results_df = pd.DataFrame(enging.daily_df)
# results_df.to_csv(f"{log_dir}/daily_results.csv", index=False)

# # 生成并保存图表
# pio.defaults.chromium_executable = "/usr/bin/google-chrome"
# fig = enging.show_chart()
# # fig.show()  # 在交互式环境中显示图表，例如 Jupyter Notebook
# fig.write_image(f"{log_dir}/backtesting_chart.png")
