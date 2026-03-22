from vnpy_ctastrategy import CtaTemplate
from vnpy.trader.object import TickData, BarData


class SimpleAgStrategy(CtaTemplate):
    """简单沪银策略：on_init加载历史，on_tick处理模拟盘Tick"""
    author = "Demo User"

    parameters = []  # 可添加参数如MA窗口
    variables = []  # 可添加变量如MA值

    def on_init(self):
        """初始化：可在此加载历史数据（从外部传入）"""
        self.write_log("策略初始化：加载历史数据完成")

    def on_start(self):
        """启动"""
        self.write_log("策略启动")

    def on_stop(self):
        """停止"""
        self.write_log("策略停止")

    def on_tick(self, tick: TickData):
        """处理模拟盘Tick：示例打印价格，可添加逻辑如下单"""
        print(f"模拟盘 Tick 更新: {tick.symbol} @ {tick.datetime}, 最新价: {tick.last_price}, 成交量: {tick.volume}")
        # 示例逻辑：if tick.last_price > some_threshold: self.buy(...)

    def on_bar(self, bar: BarData):
        """Bar 处理（可选）"""
        pass