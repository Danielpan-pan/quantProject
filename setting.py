import os
from dotenv import load_dotenv
from vnpy.trader.setting import SETTINGS

# 加载环境变量
load_dotenv()

SETTINGS["database.timezone"] = "Asia/Shanghai"
SETTINGS["datafeed.name"] = "tqsdk"
SETTINGS["datafeed.username"] = os.getenv("TQ_USERNAME", "your_tqsdk_username")
SETTINGS["datafeed.password"] = os.getenv("TQ_PASSWORD", "your_tqsdk_password")

os.environ.setdefault("LC_ALL", "C.UTF-8")
os.environ.setdefault("LANG", "C.UTF-8")
