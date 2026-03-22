from vnpy_ctastrategy import CtaTemplate


class DummyStrategy(CtaTemplate):
    author = "you"

    parameters = []
    variables = []

    def on_init(self):
        # 预热完成时被调用
        self.write_log("DummyStrategy init")

    def on_start(self):
        self.trading = True
        self.write_log("DummyStrategy start")

    def on_stop(self):
        self.trading = False
        self.write_log("DummyStrategy stop")

    def on_bar(self, bar):
        # 收到K线但不做任何交易
        print(
            f"Received bar: {bar.datetime} O:{bar.open_price} H:{bar.high_price} L:{bar.low_price} C:{bar.close_price}"
        )
        return
