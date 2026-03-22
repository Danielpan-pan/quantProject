import os
import pickle

from vnpy.trader.setting import SETTINGS

SETTINGS["datafeed.name"] = "tqsdk"  # 使用天勤数据服务
SETTINGS["datafeed.username"] = os.getenv("TQ_USERNAME", "xuanchengdaniel")
SETTINGS["datafeed.password"] = os.getenv("TQ_PASSWORD", "Panran5299.")

os.environ.setdefault("LC_ALL", "C.UTF-8")
os.environ.setdefault("LANG", "C.UTF-8")

from datetime import datetime
from vnpy.trader.object import HistoryRequest, BarData
from vnpy.trader.constant import Exchange, Interval
from vnpy.trader.datafeed import get_datafeed

symbol = "ag88"  # 沪银主连合约
level = Interval.MINUTE  # K线级别
req = HistoryRequest(
    symbol='ag',
    exchange= Exchange.PERMENENT,
    start=datetime(2024, 1, 1),
    end=datetime(2024, 12, 31),
    interval=level,
)


datafeed = get_datafeed()
# ticks = datafeed.query_tick_history(req)
bars = datafeed.query_bar_history(req)
print(len(bars))
print(bars[:3])  # 打印前3条


def convert_bar_data(original_bars):
    """将原始BarData转换为vn.py回测所需的格式"""
    converted_bars = []

    for bar in original_bars:
        # 创建新的BarData对象，修改exchange和symbol
        converted_bar = BarData(
            gateway_name=bar.gateway_name,
            symbol='ag88',  # 修改为ag88
            exchange=Exchange.SHFE,  # 修改为SHFE
            datetime=bar.datetime,
            interval=bar.interval,
            volume=bar.volume,
            turnover=bar.turnover,
            open_interest=bar.open_interest,
            open_price=bar.open_price,
            high_price=bar.high_price,
            low_price=bar.low_price,
            close_price=bar.close_price
        )
        converted_bars.append(converted_bar)

    return converted_bars


bars = convert_bar_data(bars)
print(bars[:3])  # 打印前3条

# 保存数据
with open("ag88_1m_240101_241231.pkl", "wb") as f:
    pickle.dump(bars, f)


