from datetime import datetime, time
from typing import Optional, Tuple, Dict, Any
import numpy as np
from dataclasses import dataclass
from vnpy.trader.object import BarData, TickData


@dataclass
class DynamicAnchorConfig:
    """动态锚点配置参数"""
    atr_period: int = 20  # ATR计算周期
    threshold_condition1: float = 1.2  # 条件1阈值 |Pt - MA21:30|/ATR20 ≥ 1.2
    threshold_condition2: float = 0.6  # 条件2阈值 |MA21:30 - AVWAPt|/ATR20 ≥ 0.6
    middle_interval_weight: float = 0.5  # 中间区间权重 w


class DynamicAnchorCalculator:
    """
    动态锚点计算器
    根据图片中的公式计算动态锚点 Mt
    """

    def __init__(self, config: Optional[DynamicAnchorConfig] = None):
        self.config = config or DynamicAnchorConfig()

        # 数据存储
        self.ma_2130: Optional[float] = None  # 21:30均线
        self.atr_20: Optional[float] = None  # 20日ATR
        self.avwap_t: Optional[float] = None  # 当日成交量加权平均价

        # 累计变量（用于计算AVWAP）
        self.day_pv_sum: float = 0.0  # 当日价格×成交量累计
        self.day_vol_sum: float = 0.0  # 当日成交量累计
        self.current_date: Optional[datetime] = None

        # 历史数据
        self.price_data: list = []
        self.volume_data: list = []

    def update_ma_2130(self, ma_value: float) -> None:
        """更新21:30均线值"""
        self.ma_2130 = ma_value

    def update_atr_20(self, atr_value: float) -> None:
        """更新20日ATR值"""
        self.atr_20 = atr_value

    def update_bar_data(self, bar: BarData) -> None:
        """
        更新K线数据，用于计算AVWAP
        """
        current_date = bar.datetime.date()

        # 日期切换时重置累计数据
        if self.current_date != current_date:
            self.current_date = current_date
            self.day_pv_sum = 0.0
            self.day_vol_sum = 0.0
            self.price_data = []
            self.volume_data = []

        # 累计价格和成交量
        price = (bar.open_price + bar.high_price + bar.low_price + bar.close_price) / 4
        volume = bar.volume

        self.day_pv_sum += price * volume
        self.day_vol_sum += volume
        self.price_data.append(price)
        self.volume_data.append(volume)

        # 计算当前AVWAP
        if self.day_vol_sum > 0:
            self.avwap_t = self.day_pv_sum / self.day_vol_sum

    def calculate_dynamic_anchor(self, current_price: float) -> Tuple[Optional[float], Dict[str, Any]]:
        """
        计算动态锚点 Mt

        Args:
            current_price: 当前价格 Pt

        Returns:
            Tuple[锚点值, 计算详情]
        """
        # 检查必要数据是否齐全
        if None in [self.ma_2130, self.atr_20, self.avwap_t] or self.atr_20 == 0:
            return None, {"error": "缺少必要数据", "ma_2130": self.ma_2130, "atr_20": self.atr_20,
                          "avwap_t": self.avwap_t}

        calculation_details = {
            "current_price": current_price,
            "ma_2130": self.ma_2130,
            "atr_20": self.atr_20,
            "avwap_t": self.avwap_t,
            "conditions_met": [],
            "formula_used": None
        }

        # 计算条件
        condition1 = abs(current_price - self.ma_2130) / self.atr_20 >= self.config.threshold_condition1
        condition2 = abs(self.ma_2130 - self.avwap_t) / self.atr_20 >= self.config.threshold_condition2

        calculation_details.update({
            "condition1_value": abs(current_price - self.ma_2130) / self.atr_20,
            "condition2_value": abs(self.ma_2130 - self.avwap_t) / self.atr_20,
            "condition1_met": condition1,
            "condition2_met": condition2
        })

        # 根据图片中的公式计算动态锚点
        if condition1 or condition2:
            # 条件1或条件2满足：Mt = AVWAPt
            mt = self.avwap_t
            calculation_details["formula_used"] = "Mt = AVWAPt (条件1或条件2满足)"
            calculation_details["conditions_met"].append("条件1" if condition1 else "条件2")

        else:
            # 条件均不满足时的判断
            deviation_ratio = abs(current_price - self.ma_2130) / self.atr_20

            # 这里需要定义"中间区间"的具体范围
            # 根据图片逻辑，可以假设中间区间是某个范围，比如 [0.2, 1.0]
            middle_interval_low = 0.2
            middle_interval_high = 1.0

            if middle_interval_low <= deviation_ratio < middle_interval_high:
                # 偏离处于中间区间：Mt = w * AVWAPt + (1-w) * MA21:30
                w = self.config.middle_interval_weight
                mt = w * self.avwap_t + (1 - w) * self.ma_2130
                calculation_details["formula_used"] = f"Mt = {w}×AVWAPt + {1 - w}×MA21:30 (中间区间)"
                calculation_details["deviation_ratio"] = deviation_ratio
                calculation_details["weight"] = w
            else:
                # 其他情况：Mt = MA21:30
                mt = self.ma_2130
                calculation_details["formula_used"] = "Mt = MA21:30 (条件均不满足且不在中间区间)"
                calculation_details["deviation_ratio"] = deviation_ratio

        calculation_details["dynamic_anchor"] = mt
        return mt, calculation_details

    def get_calculation_breakdown(self, current_price: float) -> Dict[str, Any]:
        """获取详细的计算分解"""
        mt, details = self.calculate_dynamic_anchor(current_price)
        return details

    def reset_daily_data(self) -> None:
        """重置每日数据"""
        self.day_pv_sum = 0.0
        self.day_vol_sum = 0.0
        self.avwap_t = None
        self.current_date = None
        self.price_data = []
        self.volume_data = []