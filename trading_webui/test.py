import sys
import os

# 将项目根目录添加到 sys.path，以便导入 strategies
current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(current_dir)
if project_root not in sys.path:
    sys.path.append(project_root)

from strategies.template import CtaTemplate
from vnpy.trader.object import TickData, BarData, OrderData, TradeData


class TestStrategy(CtaTemplate):
    """
    简单的测试策略，用于测试开平撤功能

    策略逻辑：
    1. 启动后进入阶段1：测试开仓撤单
       - 挂一个极低价格的买单
       - 等待下一个 tick 撤单
    2. 阶段2：测试开仓成交
       - 以对手价（Ask Price）+ 滑点 发送买单
       - 等待成交
    3. 阶段3：测试平仓撤单
       - 持仓后，挂一个极高价格的卖单
       - 等待下一个 tick 撤单
    4. 阶段4：测试平仓成交
       - 以对手价（Bid Price）- 滑点 发送卖单
       - 等待成交，回归空仓
    """

    author = "Copilot"

    # 定义参数
    test_volume = 1
    price_tick = 1.0

    # 定义变量
    timer_count = 0
    test_stage = 0  # 0: init, 1: test open cancel, 2: test open trade, 3: test close cancel, 4: test close trade
    last_order_id = ""

    parameters = ["test_volume", "price_tick"]
    variables = ["timer_count", "test_stage", "last_order_id"]

    def on_init(self):
        self.write_log("策略初始化")

    def on_start(self):
        self.write_log("策略启动")
        self.test_stage = 1
        self.timer_count = 0

    def on_stop(self):
        self.write_log("策略停止")

    def on_tick(self, tick: TickData):
        self.timer_count += 1

        # 每 10 个 tick 执行一次逻辑检查，避免过于频繁
        if self.timer_count % 10 != 0:
            return

        if self.test_stage == 1:
            # 阶段1: 测试开仓撤单
            if not self.last_order_id:
                # 挂一个很低的价格买入，确保不成交
                price = tick.bid_price_1 - 100 * self.price_tick
                ids = self.buy(price, self.test_volume)
                if ids:
                    self.last_order_id = ids[0]
                    self.write_log(
                        f"阶段1: 发送买入挂单 {self.last_order_id} 价格 {price}"
                    )
            else:
                # 已经发单，执行撤单
                self.cancel_order(self.last_order_id)
                self.write_log(f"阶段1: 撤销订单 {self.last_order_id}")
                # 注意：这里直接进入下一阶段，实际应该在 on_order 中确认撤单成功
                # 为了简化测试逻辑，这里假设撤单指令发出即可
                self.last_order_id = ""
                self.test_stage = 2

        elif self.test_stage == 2:
            # 阶段2: 测试开仓成交
            if self.pos == 0:
                # 以对手价+滑点买入，确保成交
                price = tick.ask_price_1 + 5 * self.price_tick
                ids = self.buy(price, self.test_volume)
                if ids:
                    self.write_log(f"阶段2: 发送买入成交单 价格 {price}")
            elif self.pos > 0:
                self.write_log(f"阶段2: 开仓成功，当前持仓 {self.pos}")
                self.test_stage = 3

        elif self.test_stage == 3:
            # 阶段3: 测试平仓撤单
            if not self.last_order_id:
                # 挂一个很高的价格卖出，确保不成交
                price = tick.ask_price_1 + 100 * self.price_tick
                ids = self.sell(price, self.test_volume)
                if ids:
                    self.last_order_id = ids[0]
                    self.write_log(
                        f"阶段3: 发送卖出挂单 {self.last_order_id} 价格 {price}"
                    )
            else:
                # 已经发单，执行撤单
                self.cancel_order(self.last_order_id)
                self.write_log(f"阶段3: 撤销订单 {self.last_order_id}")
                self.last_order_id = ""
                self.test_stage = 4

        elif self.test_stage == 4:
            # 阶段4: 测试平仓成交
            if self.pos > 0:
                # 以对手价-滑点卖出，确保成交
                price = tick.bid_price_1 - 5 * self.price_tick
                ids = self.sell(price, self.test_volume)
                if ids:
                    self.write_log(f"阶段4: 发送卖出成交单 价格 {price}")
            elif self.pos == 0:
                self.write_log("阶段4: 平仓成功，测试完成")
                self.test_stage = 5

    def on_order(self, order: OrderData):
        # 可以在这里处理订单状态更新
        pass

    def on_trade(self, trade: TradeData):
        self.write_log(
            f"成交回报: {trade.direction} {trade.offset} 价格 {trade.price} 数量 {trade.volume}"
        )

    def on_bar(self, bar: BarData):
        pass
