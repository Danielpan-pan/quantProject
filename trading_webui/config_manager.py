"""
配置管理模块
管理系统配置、阈值参数、连接设置等
"""

import json
import os
from typing import Dict, Any, Optional
from pathlib import Path
import logging


class ConfigManager:
    """配置管理器"""

    DEFAULT_CONFIG = {
        # CTP 连接配置
        "ctp": {
            "trade_server": "",
            "market_server": "",
            "broker_id": "",
            "userid": "",
            "password": "",
            "appid": "",
            "authcode": "",
            "product_info": "",
            "environment": "test",  # test 或 production
        },
        # 风控阈值配置
        "risk": {
            "enabled": True,
            "repeat_open_threshold": 10,
            "repeat_close_threshold": 10,
            "repeat_cancel_threshold": 10,
            "repeat_time_window": 60,
            "total_order_threshold": 1000,
            "total_cancel_threshold": 500,
            "total_time_period": "day",
            "max_order_volume": 100,
        },
        # 校验规则配置
        "validation": {
            "check_contract": True,
            "check_tick_size": True,
            "check_max_volume": True,
            "check_balance": True,
            "check_position": True,
            "check_market_status": True,
        },
        # 告警配置
        "alert": {
            "enable_sound": True,
            "enable_popup": True,
            "enable_email": False,
            "enable_sms": False,
            "email_recipients": [],
            "sms_recipients": [],
        },
        # 交易配置
        "trading": {
            "default_strategy": "",
            "default_symbols": [],
            "auto_start": False,
            "enable_backtesting": True,
        },
        # 订阅配置
        "subscriptions": [],
        # 日志配置
        "logging": {
            "level": "INFO",
            "file_path": "logs/trading.log",
            "max_file_size": 10485760,  # 10MB
            "backup_count": 10,
            "console_output": True,
        },
        # WebUI 配置
        "webui": {
            "host": "0.0.0.0",
            "port": 8080,
            "debug": False,
            "secret_key": "vnpy-trading-webui-secret-key-change-this",
        },
    }

    def __init__(self, config_file: str = "config.json"):
        self.config_file = Path(config_file)
        self.config: Dict[str, Any] = {}
        self.logger = logging.getLogger("ConfigManager")

        # 加载配置
        self.load_config()

    def load_config(self) -> bool:
        """加载配置文件"""
        try:
            if self.config_file.exists():
                with open(self.config_file, "r", encoding="utf-8") as f:
                    loaded_config = json.load(f)

                # 合并默认配置和加载的配置
                self.config = self._merge_config(
                    self.DEFAULT_CONFIG.copy(), loaded_config
                )
                self.logger.info(f"配置已从 {self.config_file} 加载")
                return True
            else:
                # 使用默认配置
                self.config = self.DEFAULT_CONFIG.copy()
                self.logger.warning(f"配置文件 {self.config_file} 不存在，使用默认配置")

                # 创建默认配置文件
                self.save_config()
                return False
        except Exception as e:
            self.logger.error(f"加载配置失败: {e}")
            self.config = self.DEFAULT_CONFIG.copy()
            return False

    def _merge_config(self, base: Dict, override: Dict) -> Dict:
        """递归合并配置"""
        result = base.copy()
        for key, value in override.items():
            if (
                key in result
                and isinstance(result[key], dict)
                and isinstance(value, dict)
            ):
                result[key] = self._merge_config(result[key], value)
            else:
                result[key] = value
        return result

    def save_config(self) -> bool:
        """保存配置文件"""
        try:
            # 确保目录存在
            self.config_file.parent.mkdir(parents=True, exist_ok=True)

            with open(self.config_file, "w", encoding="utf-8") as f:
                json.dump(self.config, f, indent=2, ensure_ascii=False)

            self.logger.info(f"配置已保存到 {self.config_file}")
            return True
        except Exception as e:
            self.logger.error(f"保存配置失败: {e}")
            return False

    def get(self, key: str, default: Any = None) -> Any:
        """获取配置值（支持点号分隔的嵌套键）"""
        keys = key.split(".")
        value = self.config

        for k in keys:
            if isinstance(value, dict) and k in value:
                value = value[k]
            else:
                return default

        return value

    def set(self, key: str, value: Any, save: bool = True) -> bool:
        """设置配置值（支持点号分隔的嵌套键）"""
        keys = key.split(".")
        config = self.config

        # 导航到最后一级
        for k in keys[:-1]:
            if k not in config:
                config[k] = {}
            config = config[k]

        # 设置值
        config[keys[-1]] = value

        if save:
            return self.save_config()

        return True

    def update(self, updates: Dict[str, Any], save: bool = True) -> bool:
        """批量更新配置"""
        try:
            for key, value in updates.items():
                self.set(key, value, save=False)

            if save:
                return self.save_config()

            return True
        except Exception as e:
            self.logger.error(f"更新配置失败: {e}")
            return False

    def get_ctp_config(self) -> Dict[str, str]:
        """获取 CTP 连接配置（VNPY 格式）"""
        ctp_config = self.get("ctp", {})

        # 处理环境配置
        env = ctp_config.get("environment", "test")
        env_cn = "实盘" if env == "production" else "测试"

        return {
            "交易服务器": ctp_config.get("trade_server", ""),
            "行情服务器": ctp_config.get("market_server", ""),
            "经纪商代码": ctp_config.get("broker_id", ""),
            "用户名": ctp_config.get("userid", ""),
            "密码": ctp_config.get("password", ""),
            "产品名称": ctp_config.get("appid", ""),
            "授权编码": ctp_config.get("authcode", ""),
            "产品信息": ctp_config.get("product_info", ""),
            "柜台环境": env_cn,
        }

    def update_ctp_config(self, ctp_config: Dict[str, str], save: bool = True) -> bool:
        """更新 CTP 连接配置"""
        mapping = {
            "交易服务器": "trade_server",
            "行情服务器": "market_server",
            "经纪商代码": "broker_id",
            "用户名": "userid",
            "密码": "password",
            "产品名称": "appid",
            "授权编码": "authcode",
            "产品信息": "product_info",
        }

        updates = {}
        for cn_key, en_key in mapping.items():
            if cn_key in ctp_config:
                updates[f"ctp.{en_key}"] = ctp_config[cn_key]

        # 特殊处理柜台环境
        if "柜台环境" in ctp_config:
            env_cn = ctp_config["柜台环境"]
            env = "production" if env_cn == "实盘" else "test"
            updates["ctp.environment"] = env

        return self.update(updates, save=save)

    def get_risk_config(self) -> Dict[str, Any]:
        """获取风控配置"""
        return self.get("risk", {})

    def update_risk_config(
        self, risk_config: Dict[str, Any], save: bool = True
    ) -> bool:
        """更新风控配置"""
        updates = {f"risk.{k}": v for k, v in risk_config.items()}
        return self.update(updates, save=save)

    def get_validation_config(self) -> Dict[str, bool]:
        """获取校验配置"""
        return self.get("validation", {})

    def update_validation_config(
        self, validation_config: Dict[str, bool], save: bool = True
    ) -> bool:
        """更新校验配置"""
        updates = {f"validation.{k}": v for k, v in validation_config.items()}
        return self.update(updates, save=save)

    def get_alert_config(self) -> Dict[str, Any]:
        """获取告警配置"""
        return self.get("alert", {})

    def update_alert_config(
        self, alert_config: Dict[str, Any], save: bool = True
    ) -> bool:
        """更新告警配置"""
        updates = {f"alert.{k}": v for k, v in alert_config.items()}
        return self.update(updates, save=save)

    def get_logging_config(self) -> Dict[str, Any]:
        """获取日志配置"""
        return self.get("logging", {})

    def get_webui_config(self) -> Dict[str, Any]:
        """获取 WebUI 配置"""
        return self.get("webui", {})

    def validate_config(self) -> tuple[bool, list[str]]:
        """验证配置完整性"""
        errors = []

        # 检查 CTP 配置
        ctp_config = self.get("ctp", {})
        required_ctp_fields = [
            "trade_server",
            "market_server",
            "broker_id",
            "userid",
            "password",
        ]
        for field in required_ctp_fields:
            if not ctp_config.get(field):
                errors.append(f"CTP 配置缺少必填字段: {field}")

        # 检查风控配置
        risk_config = self.get("risk", {})
        if risk_config.get("repeat_time_window", 0) <= 0:
            errors.append("重复报单时间窗口必须大于0")

        if risk_config.get("max_order_volume", 0) <= 0:
            errors.append("单笔最大手数必须大于0")

        # 检查日志配置
        logging_config = self.get("logging", {})
        log_file = logging_config.get("file_path")
        if log_file:
            log_dir = Path(log_file).parent
            if not log_dir.exists():
                try:
                    log_dir.mkdir(parents=True, exist_ok=True)
                except Exception as e:
                    errors.append(f"无法创建日志目录: {e}")

        return len(errors) == 0, errors

    def export_config(self, export_path: str) -> bool:
        """导出配置到指定文件"""
        try:
            export_file = Path(export_path)
            export_file.parent.mkdir(parents=True, exist_ok=True)

            with open(export_file, "w", encoding="utf-8") as f:
                json.dump(self.config, f, indent=2, ensure_ascii=False)

            self.logger.info(f"配置已导出到 {export_file}")
            return True
        except Exception as e:
            self.logger.error(f"导出配置失败: {e}")
            return False

    def import_config(self, import_path: str, save: bool = True) -> bool:
        """从指定文件导入配置"""
        try:
            import_file = Path(import_path)
            if not import_file.exists():
                self.logger.error(f"导入文件不存在: {import_file}")
                return False

            with open(import_file, "r", encoding="utf-8") as f:
                imported_config = json.load(f)

            # 合并配置
            self.config = self._merge_config(self.config, imported_config)

            if save:
                self.save_config()

            self.logger.info(f"配置已从 {import_file} 导入")
            return True
        except Exception as e:
            self.logger.error(f"导入配置失败: {e}")
            return False

    def reset_to_default(self, save: bool = True) -> bool:
        """重置为默认配置"""
        self.config = self.DEFAULT_CONFIG.copy()

        if save:
            return self.save_config()

        self.logger.info("配置已重置为默认值")
        return True

    def get_all_config(self) -> Dict[str, Any]:
        """获取所有配置"""
        return self.config.copy()

    def get_subscriptions(self) -> list:
        """获取订阅列表"""
        return self.get("subscriptions", [])

    def add_subscription(self, symbol: str, exchange: str, save: bool = True) -> bool:
        """添加订阅"""
        subscriptions = self.get_subscriptions()
        subscription = {"symbol": symbol, "exchange": exchange}

        # 检查是否已存在
        if subscription not in subscriptions:
            subscriptions.append(subscription)
            self.set("subscriptions", subscriptions, save=save)
            return True
        return False

    def remove_subscription(
        self, symbol: str, exchange: str, save: bool = True
    ) -> bool:
        """移除订阅"""
        subscriptions = self.get_subscriptions()
        subscription = {"symbol": symbol, "exchange": exchange}

        if subscription in subscriptions:
            subscriptions.remove(subscription)
            self.set("subscriptions", subscriptions, save=save)
            return True
        return False

    def clear_subscriptions(self, save: bool = True) -> bool:
        """清空订阅"""
        self.set("subscriptions", [], save=save)
        return True

    def load_from_env(self) -> bool:
        """从环境变量加载配置（优先级高于文件）"""
        try:
            # CTP 配置
            env_mappings = {
                "CTP_TRADE_SERVER": "ctp.trade_server",
                "CTP_MARKET_SERVER": "ctp.market_server",
                "CTP_BROKER_ID": "ctp.broker_id",
                "CTP_USERID": "ctp.userid",
                "CTP_PASSWORD": "ctp.password",
                "CTP_APPID": "ctp.appid",
                "CTP_AUTHCODE": "ctp.authcode",
                "CTP_PRODUCT_INFO": "ctp.product_info",
                "CTP_ENVIRONMENT": "ctp.environment",
                "WEBUI_PORT": "webui.port",
                "WEBUI_HOST": "webui.host",
            }

            for env_key, config_key in env_mappings.items():
                env_value = os.getenv(env_key)
                if env_value:
                    # 处理数字类型
                    if config_key == "webui.port":
                        env_value = int(env_value)
                    self.set(config_key, env_value, save=False)

            self.logger.info("已从环境变量加载配置")
            return True
        except Exception as e:
            self.logger.error(f"从环境变量加载配置失败: {e}")
            return False
