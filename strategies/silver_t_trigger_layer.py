# trigger_layer.py
from collections import deque
from datetime import time, date, datetime, timedelta
from typing import Dict, List
import numpy as np
from vnpy_ctastrategy import ArrayManager, BarData


class TriggerLayer:
    """
    触发层模块 - 负责动态阈值计算和锚点管理
    """

    def __init__(self, base_threshold: float = 50.0):
        """
        初始化触发层

        Args:
            base_threshold: 基准阈值
        """
        self.base_threshold = base_threshold

        # 触发层变量
        self.current_threshold: float = 0.0  # 当前动态阈值
        self.atr_t: float = 0.0  # 晚盘21:00-21:30的ATR
        self.atr_t_calculated: bool = False  # 是否已计算晚盘ATR
        self.atr_t_am: ArrayManager = ArrayManager(size=30)  # 用于计算晚盘ATR的ArrayManager

        # 新增：30分钟成交量窗口相关变量
        self.volume_window: deque = deque(maxlen=30)  # 存储最近30分钟的成交量
        self.volume_timestamps: deque = deque(maxlen=30)  # 存储对应的时间戳
        self.qt = 0

        # 时间窗口定义
        self.anchor_window_start = time(21, 0)
        self.anchor_window_end = time(21, 30)

    def calculate_volume_quantile_last_30min(self, current_volume: float, current_dt: datetime) -> float:
        """
        计算当前分钟成交量在过去30分钟成交量中的百分位排名

        Args:
            current_volume: 当前分钟成交量
            current_dt: 当前时间戳

        Returns:
            float: 成交量分位 (0-1之间)
        """
        # 清理超过30分钟的数据
        self._clean_old_volume_data(current_dt)

        # 添加当前数据到窗口
        self.volume_window.append(current_volume)
        self.volume_timestamps.append(current_dt)

        # 如果数据不足，返回默认值
        if len(self.volume_window) <= 5:  # 至少需要5个数据点
            return 0.5

        # 计算百分位排名
        result = self._compute_percentile_rank(current_volume, list(self.volume_window))
        return result

    def _clean_old_volume_data(self, current_dt: datetime) -> None:
        """
        清理超过30分钟的旧数据

        Args:
            current_dt: 当前时间戳
        """
        # 计算30分钟前的时间点
        threshold_time = current_dt - timedelta(minutes=30)

        # 移除超过30分钟的数据
        while self.volume_timestamps and self.volume_timestamps[0] < threshold_time:
            self.volume_timestamps.popleft()
            self.volume_window.popleft()

    def _compute_percentile_rank(self, current_value: float, historical_data: List[float]) -> float:
        """
        计算当前值在历史数据中的百分位排名

        Args:
            current_value: 当前值
            historical_data: 历史数据列表

        Returns:
            float: 百分位排名 (0-1)
        """
        if not historical_data:
            return 0.5

        # 计算小于和等于当前值的数量
        less_count = sum(1 for x in historical_data if x < current_value)
        equal_count = sum(1 for x in historical_data if x == current_value)

        # 百分位排名公式: (小于当前值的数量 + 0.5 * 等于当前值的数量) / 总数量
        total_count = len(historical_data)
        percentile_rank = (less_count + 0.5 * equal_count) / total_count

        return percentile_rank

    def get_volume_window_info(self) -> Dict:
        """
        获取成交量窗口相关信息

        Returns:
            Dict: 成交量窗口信息
        """
        return {
            'window_size': len(self.volume_window),
            'min_volume': min(self.volume_window) if self.volume_window else 0,
            'max_volume': max(self.volume_window) if self.volume_window else 0,
            'avg_volume': np.mean(self.volume_window) if self.volume_window else 0,
            'timestamps_count': len(self.volume_timestamps)
        }

    # 以下为原有函数，保持不变
    def calculate_atr_t(self, bar: BarData) -> None:
        """
        计算晚盘21:00-21:30时段的ATR

        Args:
            bar: K线数据
        """
        bar_time = bar.datetime.time()

        # 如果在21:00-21:30时段内，收集数据计算ATR
        if self.anchor_window_start <= bar_time <= self.anchor_window_end:
            # 重置标志（如果是新的一天的21:00）
            if bar_time == self.anchor_window_start:
                self.atr_t_calculated = False
                # 重置ArrayManager以开始新一天的数据收集
                self.atr_t_am = ArrayManager(size=30)

            # 更新ArrayManager
            self.atr_t_am.update_bar(bar)

            # 在21:30时计算ATR
            if bar_time == self.anchor_window_end and self.atr_t_am.inited:
                # 计算20周期ATR
                self.atr_t = float(self.atr_t_am.atr(20))
                self.atr_t_calculated = True

    def calculate_dynamic_threshold(self, bar: BarData, atr_value: float) -> float:
        """
        计算动态阈值


        Returns:
            float: 动态阈值
        """
        # 首先计算当前成交量分位
        self.qt = self.calculate_volume_quantile_last_30min(bar.volume, bar.datetime)

        # 获取时间段系数
        time_coeffs = self._get_time_coefficients(bar.datetime.time())
        a1 = time_coeffs['a1']  # ATR系数
        a2 = time_coeffs['a2']  # 成交量系数

        if self.atr_t_calculated and self.atr_t > 0:
            atr_ratio = self.atr_t /atr_value
        else:
            # 如果晚盘ATR_t尚未计算，使用默认值1.0
            atr_ratio = 1.0

        # 动态阈值公式: Θ_t = θ_0 * [1 + a1*(ATR_t/ATR_2130 - 1) + a2*(q_t - 0.5)]
        # print(self.atr_t, atr_ratio)
        adjustment = 1.0 + a1 * (atr_ratio - 1.0)
        self.current_threshold = self.base_threshold * adjustment
        print(self.current_threshold, adjustment,atr_ratio, a1, a2)
        return self.current_threshold

    def _get_time_coefficients(self, current_time: time) -> Dict[str, float]:
        """
        根据时间段返回系数

        Args:
            current_time: 当前时间

        Returns:
            Dict: 包含a1和a2系数的字典
        """
        # 早盘 (09:00-10:00)
        if time(9, 0) <= current_time < time(10, 0):
            return {'a1': 0.6, 'a2': 0.4}
        # 主窗 (10:30-11:30)
        elif time(10, 30) <= current_time < time(11, 30):
            return {'a1': 0.4, 'a2': 0.2}
        # 夜盘 (21:00-23:00)
        elif time(21, 0) <= current_time < time(23, 0):
            return {'a1': 0.5, 'a2': 0.3}
        # 其他时段
        else:
            return {'a1': 0.5, 'a2': 0.3}


    def get_threshold_info(self) -> Dict[str, float]:
        """
        获取阈值相关信息

        Returns:
            Dict: 包含所有阈值相关信息的字典
        """
        # 获取成交量窗口信息
        volume_info = self.get_volume_window_info()


        # 返回所有相关变量，使用中文键名
        return {
            '计算后波动阈值': self.current_threshold,
            '晚盘30分钟ATR值': self.atr_t,
            '基础阈值': self.base_threshold,
            '成交量分位值': self.qt,
            '成交量窗口大小': volume_info['window_size'],
            '最小成交量': volume_info['min_volume'],
            '最大成交量': volume_info['max_volume'],
            '平均成交量': volume_info['avg_volume'],
            '时间戳数量': volume_info['timestamps_count']
        }

