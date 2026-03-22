import atexit
import json
import logging
import os
import queue
import socket
import threading
import time
import uuid
from datetime import datetime, timezone
from logging.handlers import RotatingFileHandler, TimedRotatingFileHandler
from typing import Any, Dict, List, Optional, Union

import pandas as pd
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from vnpy.event.engine import Event, EventEngine
from vnpy.trader.engine import (
    BaseEngine,
    MainEngine,
    LogData,
    EVENT_LOG,
    DEBUG,
    INFO,
    WARNING,
    ERROR,
    CRITICAL,
)

# ---- RunLogger global registry for cross-module access ----
_CURRENT_RUN_LOGGER = None


def set_current_run_logger(rl):
    global _CURRENT_RUN_LOGGER
    _CURRENT_RUN_LOGGER = rl


def get_current_run_logger():
    return _CURRENT_RUN_LOGGER


class DBAsyncWriter:
    """将 LogRecord 批量落库的异步线程（低耦合、高吞吐）。"""

    def __init__(
        self,
        engine: Engine,
        experiment_id: uuid.UUID,
        batch_size: int = 200,
        flush_seconds: float = 1.0,
    ):
        self.engine = engine
        self.experiment_id = experiment_id
        self.batch_size = batch_size
        self.flush_seconds = flush_seconds
        self.q: "queue.Queue[logging.LogRecord]" = queue.Queue(maxsize=10000)
        self._stop = threading.Event()
        self._th = threading.Thread(target=self._run, name="DBAsyncWriter", daemon=True)
        self._th.start()

    def put(self, record: logging.LogRecord):
        try:
            self.q.put_nowait(record)
        except queue.Full:
            # 丢弃或降级处理：这里选择丢弃最旧，保证系统不被打爆
            try:
                self.q.get_nowait()
                self.q.put_nowait(record)
            except queue.Empty:
                pass

    def _run(self):
        buf: List[logging.LogRecord] = []
        deadline = time.time() + self.flush_seconds
        while not self._stop.is_set():
            timeout = max(0, deadline - time.time())
            try:
                rec = self.q.get(timeout=timeout)
                buf.append(rec)
                if len(buf) >= self.batch_size:
                    self._flush(buf)
                    buf.clear()
                    deadline = time.time() + self.flush_seconds
            except queue.Empty:
                if buf:
                    self._flush(buf)
                    buf.clear()
                deadline = time.time() + self.flush_seconds

        # 退出前 flush
        if buf:
            self._flush(buf)

    def _flush(self, records: List[logging.LogRecord]):
        rows = []
        for r in records:
            # 将 LogRecord 映射为 DB 行
            ts = datetime.fromtimestamp(r.created, tz=timezone.utc)
            msg = r.getMessage()
            strategy = getattr(r, "strategy", None)
            extra_keys = {"strategy", "exp_id"}  # exp_id 也在 extra 里
            extras: Dict[str, Any] = {
                k: v
                for k, v in r.__dict__.items()
                if k
                not in vars(logging.LogRecord("", 0, "", "", None, (), None)).keys()
                and k not in extra_keys
            }
            rows.append(
                {
                    "ts": ts,
                    "experiment_id": str(self.experiment_id),
                    "level": r.levelname,
                    "logger_name": r.name,
                    "message": msg,
                    "strategy": strategy,
                    "pathname": r.pathname,
                    "lineno": r.lineno,
                    "func": r.funcName,
                    "extra": json.dumps(extras) if extras else None,
                }
            )

        if not rows:
            return
        sql = text("""
            INSERT INTO logs (ts, experiment_id, level, logger_name, message, strategy, pathname, lineno, func, extra)
            VALUES (:ts, :experiment_id, :level, :logger_name, :message, :strategy, :pathname, :lineno, :func, CAST(:extra AS jsonb))
        """)
        try:
            with self.engine.begin() as conn:
                conn.execute(sql, rows)
        except Exception as e:
            # 仅打印一次，避免递归 logging
            print(f"[DBAsyncWriter] insert failed: {e}")

    def stop(self):
        self._stop.set()
        self._th.join(timeout=3)


class RunLogger:
    """
    为每次运行分配唯一 experiment_id，日志文件+数据库双写，目录/元数据规范化。
    """

    def __init__(
        self,
        log_root: str = "logs",
        run_prefix: str = "sim_testing",
        level: int = logging.DEBUG,
        console: bool = True,
        rotate: Optional[Union[bool, str]] = None,
        max_bytes: int = 5 * 1024 * 1024,
        backup_count: int = 7,
        db_dsn: Optional[str] = None,  # postgresql+psycopg://user:pass@host:5432/db
        db_init_schema: bool = False,  # 是否在启动时自动建表（生产可关）
        run_params: Optional[
            Dict[str, Any]
        ] = None,  # 可选：实验参数（会写进 experiments.params）
        tags: Optional[List[str]] = None,  # 可选：标签
    ):
        self.experiment_id: uuid.UUID = uuid.uuid4()
        self.exp_id_short = str(self.experiment_id).split("-")[0]
        ts = time.strftime("%Y%m%d-%H%M%S")

        # 目录形如：logs/<run_prefix>/<YYYYmmdd-HHMMSS>_<expid>
        self.log_dir = os.path.join(log_root, f"{run_prefix}/{ts}_{self.exp_id_short}")
        os.makedirs(self.log_dir, exist_ok=True)
        self.log_name = f"{run_prefix}.log"
        self.log_path = os.path.join(self.log_dir, self.log_name)

        # 核心 logger
        self.logger = logging.getLogger(f"{run_prefix}-{ts}-{self.exp_id_short}")
        self.logger.setLevel(level)
        self.logger.propagate = False

        # 统一在 record.extra 里带 exp_id，格式化串可直接引用
        class _ExpIdFilter(logging.Filter):
            def filter(_self, record: logging.LogRecord):
                setattr(record, "exp_id", self.exp_id_short)
                return True

        self.exp_filter = _ExpIdFilter()

        if not self.logger.handlers:
            # 文件 handler（保留原来逻辑）
            if rotate is True:
                rotate = "time"

            if rotate == "size":
                fh = RotatingFileHandler(
                    self.log_path,
                    maxBytes=max_bytes,
                    backupCount=backup_count,
                    encoding="utf-8",
                )
            elif rotate == "time":
                fh = TimedRotatingFileHandler(
                    self.log_path,
                    when="midnight",
                    backupCount=backup_count,
                    encoding="utf-8",
                )
            else:
                fh = logging.FileHandler(self.log_path, encoding="utf-8")

            fmt = logging.Formatter(
                "%(asctime)s - %(levelname)s - [exp=%(exp_id)s] - %(message)s"
            )
            fh.setFormatter(fmt)
            fh.addFilter(self.exp_filter)
            self.logger.addHandler(fh)

            if console:
                ch = logging.StreamHandler()
                ch.setLevel(logging.INFO)
                ch.setFormatter(fmt)
                ch.addFilter(self.exp_filter)
                self.logger.addHandler(ch)

        # 数据库：可选
        self.engine: Optional[Engine] = None
        self.db_writer: Optional[DBAsyncWriter] = None
        if db_dsn:
            self.engine = create_engine(db_dsn, pool_pre_ping=True)
            if db_init_schema:
                self._init_db_schema()
            self._register_experiment(run_prefix, ts, run_params, tags)
            self.db_writer = DBAsyncWriter(self.engine, self.experiment_id)

            # 再加一个“只写 DB 的 handler”，通过队列异步写
            class _DBHandler(logging.Handler):
                def emit(_self, record: logging.LogRecord):
                    if self.db_writer:
                        self.db_writer.put(record)

            dbh = _DBHandler()
            dbh.addFilter(self.exp_filter)
            self.logger.addHandler(dbh)

        # 让其它模块（如策略）可以取到当前 RunLogger
        try:
            set_current_run_logger(self)
        except Exception:
            pass

        # 元数据落盘，便于排障
        self._dump_metadata(run_prefix, ts, run_params, tags)

        # 退出时确保 flush
        atexit.register(self.close)

    def upsert_bar_1m_rows(self, rows: List[Dict[str, Any]]):
        """
        批量写入/更新 1m K 线到 bar_1m（需要在初始化时提供 db_dsn）。
        每条记录需包含: ts(datetime/tz-aware), symbol, strategy_id, account_id,
        open, high, low, close, volume, turnover。
        experiment_id 将自动补充为当前 run 的 experiment_id。
        """
        if not self.engine:
            return
        if not rows:
            return

        def _normalize_ts(dt):
            # 允许 naive；naive 视为 UTC
            if isinstance(dt, datetime):
                return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
            return pd.to_datetime(dt, utc=True).to_pydatetime()

        normed = []
        for r in rows:
            item = dict(r)
            item["experiment_id"] = str(self.experiment_id)
            item["ts"] = _normalize_ts(item["ts"])
            # 容错：空字段默认 0
            for k in ("open", "high", "low", "close", "volume", "turnover"):
                if k in item and item[k] is None:
                    item[k] = 0.0
            normed.append(item)

        sql = text("""
        INSERT INTO bar_1m (ts, symbol, strategy_id, account_id, open, high, low, close, volume, turnover, experiment_id)
        VALUES (:ts, :symbol, :strategy_id, :account_id, :open, :high, :low, :close, :volume, :turnover, :experiment_id)
        ON CONFLICT (ts, symbol, strategy_id, account_id, experiment_id)
        DO UPDATE SET
          open = EXCLUDED.open,
          high = EXCLUDED.high,
          low  = EXCLUDED.low,
          close= EXCLUDED.close,
          volume = EXCLUDED.volume,
          turnover = EXCLUDED.turnover
        """)
        try:
            with self.engine.begin() as conn:
                conn.execute(sql, normed)
        except Exception as e:
            print(f"[RunLogger.upsert_bar_1m_rows] failed: {e}")

    def upsert_bar_1m_from_bar(
        self,
        bar_obj,
        strategy_id: str,
        account_id: str,
        contract_size: float,
        symbol: Optional[str] = None,
    ):
        """
        直接从 vn.py 的 BarData 填充并写入 bar_1m。
        turnover≈close*volume*contract_size。
        """
        if not self.engine:
            return
        try:
            ts = getattr(bar_obj, "datetime")
            symbol = (
                symbol
                or getattr(bar_obj, "vt_symbol", None)
                or getattr(self, "symbol", None)
                or "UNKNOWN"
            )
            o = float(getattr(bar_obj, "open_price"))
            h = float(getattr(bar_obj, "high_price"))
            l = float(getattr(bar_obj, "low_price"))
            c = float(getattr(bar_obj, "close_price"))
            v = float(getattr(bar_obj, "volume", 0.0) or 0.0)
            turnover = float(c) * float(v) * float(contract_size or 1.0)
            row = {
                "ts": ts,
                "symbol": symbol,
                "strategy_id": strategy_id,
                "account_id": account_id,
                "open": o,
                "high": h,
                "low": l,
                "close": c,
                "volume": v,
                "turnover": turnover,
            }
            self.upsert_bar_1m_rows([row])
        except Exception as e:
            print(f"[RunLogger.upsert_bar_1m_from_bar] failed: {e}")

    # ====== 基本 API ======
    def log(self, level: str, msg: str, *args, **kwargs):
        if level == "DEBUG":
            self.debug(msg, *args, **kwargs)
        elif level == "INFO":
            self.info(msg, *args, **kwargs)
        elif level == "WARNING":
            self.warning(msg, *args, **kwargs)
        elif level == "ERROR":
            self.error(msg, *args, **kwargs)
        elif level == "CRITICAL":
            self.error(msg, *args, **kwargs)
        else:
            self.info(msg, *args, **kwargs)

    def debug(self, msg: str, *args, **kwargs):
        self.logger.debug(msg, *args, **kwargs)

    def info(self, msg: str, *args, **kwargs):
        self.logger.info(msg, *args, **kwargs)

    def warning(self, msg: str, *args, **kwargs):
        self.logger.warning(msg, *args, **kwargs)

    def error(self, msg: str, *args, **kwargs):
        self.logger.error(msg, *args, **kwargs)

    def exception(self, msg: str, *args, **kwargs):
        self.logger.exception(msg, *args, **kwargs)

    def for_strategy(self, strategy_name: str) -> logging.LoggerAdapter:
        """返回带 strategy 的 LoggerAdapter；DB 会把 strategy 作为结构化字段写入。"""

        class _Adapter(logging.LoggerAdapter):
            def process(self, msg, kwargs):
                # 显示前缀便于文件阅读，同时把 strategy 放入 extra
                kwargs.setdefault("extra", {})
                kwargs["extra"].setdefault("strategy", strategy_name)
                return f"{strategy_name}: {msg}", kwargs

        return _Adapter(self.logger, {"strategy": strategy_name})

    def close(self):
        """进程退出或切换实验时调用，确保 DB 队列 flush。"""
        for h in list(self.logger.handlers):
            try:
                h.flush()
            except Exception:
                pass
        if self.db_writer:
            self.db_writer.stop()
        # 不移除 handlers，避免多次 close 异常

    # ====== 内部：DB 与元数据 ======
    def _init_db_schema(self):
        ddl = """
        CREATE EXTENSION IF NOT EXISTS timescaledb;
        CREATE TABLE IF NOT EXISTS experiments(
          experiment_id uuid PRIMARY KEY,
          run_prefix text NOT NULL,
          started_at timestamptz NOT NULL DEFAULT now(),
          log_dir text NOT NULL,
          params jsonb, tags text[], hostname text, git_commit text, notes text
        );
        CREATE TABLE IF NOT EXISTS logs(
          ts timestamptz NOT NULL,
          experiment_id uuid NOT NULL REFERENCES experiments(experiment_id) ON DELETE CASCADE,
          level text NOT NULL, logger_name text, message text NOT NULL,
          strategy text, pathname text, lineno int, func text, extra jsonb
        );
        SELECT create_hypertable('logs','ts', if_not_exists => true, migrate_data => true);
        CREATE INDEX IF NOT EXISTS idx_logs_exp_ts ON logs (experiment_id, ts DESC);
        CREATE INDEX IF NOT EXISTS idx_logs_level  ON logs (level);
        -- 1m K 线表，含 experiment_id 作为维度
        CREATE TABLE IF NOT EXISTS bar_1m (
          ts             timestamptz      NOT NULL,
          symbol         text             NOT NULL,
          strategy_id    text             NOT NULL,
          account_id     text             NOT NULL,
          open           double precision NOT NULL,
          high           double precision NOT NULL,
          low            double precision  NOT NULL,
          close          double precision  NOT NULL,
          volume         double precision  DEFAULT 0,
          turnover       double precision  DEFAULT 0,
          experiment_id  uuid             NOT NULL,
          PRIMARY KEY (ts, symbol, strategy_id, account_id, experiment_id)
        );
        SELECT create_hypertable('bar_1m','ts', if_not_exists => true, migrate_data => true);
        CREATE INDEX IF NOT EXISTS idx_bar_1m_exp_ts    ON bar_1m (experiment_id, ts DESC);
        CREATE INDEX IF NOT EXISTS idx_bar_1m_symbol_ts ON bar_1m (symbol, ts DESC);
        """
        with self.engine.begin() as conn:
            conn.exec_driver_sql(ddl)

    def _register_experiment(
        self,
        run_prefix: str,
        ts_str: str,
        params: Optional[Dict[str, Any]],
        tags: Optional[List[str]],
    ):
        # 尝试获取 git commit（非必须）
        git_commit = None
        try:
            import subprocess

            git_commit = (
                subprocess.check_output(
                    ["git", "rev-parse", "--short", "HEAD"], stderr=subprocess.DEVNULL
                )
                .decode()
                .strip()
            )
        except Exception:
            pass

        sql = text("""
            INSERT INTO experiments (experiment_id, run_prefix, started_at, log_dir, params, tags, hostname, git_commit)
            VALUES (:experiment_id, :run_prefix, now(), :log_dir, CAST(:params AS jsonb), :tags, :hostname, :git_commit)
            ON CONFLICT (experiment_id) DO NOTHING
        """)
        with self.engine.begin() as conn:
            conn.execute(
                sql,
                {
                    "experiment_id": str(self.experiment_id),
                    "run_prefix": run_prefix,
                    "log_dir": self.log_dir,
                    "params": json.dumps(params or {}),
                    "tags": tags or [],
                    "hostname": socket.gethostname(),
                    "git_commit": git_commit,
                },
            )

    def _dump_metadata(
        self,
        run_prefix: str,
        ts_str: str,
        params: Optional[Dict[str, Any]],
        tags: Optional[List[str]],
    ):
        meta = {
            "experiment_id": str(self.experiment_id),
            "run_prefix": run_prefix,
            "started_at": datetime.utcnow().isoformat() + "Z",
            "log_dir": self.log_dir,
            "log_path": self.log_path,
            "params": params or {},
            "tags": tags or [],
            "hostname": socket.gethostname(),
            "pid": os.getpid(),
        }
        with open(
            os.path.join(self.log_dir, "metadata.json"), "w", encoding="utf-8"
        ) as f:
            json.dump(meta, f, ensure_ascii=False, indent=2)


class DummyRunLogger:
    """空实现的 RunLogger，避免没有 logger 时的异常。"""

    def __init__(self):
        self.experiment_id = None

    def debug(self, msg: str, *args, **kwargs):
        pass

    def info(self, msg: str, *args, **kwargs):
        pass

    def warning(self, msg: str, *args, **kwargs):
        pass

    def error(self, msg: str, *args, **kwargs):
        pass

    def critical(self, msg: str, *args, **kwargs):
        pass


class RecordEngine(BaseEngine):
    """
    RecordEngine is a custom log engine that records log events to the RunLogger.
    """

    level_map: dict[int, str] = {
        DEBUG: "DEBUG",
        INFO: "INFO",
        WARNING: "WARNING",
        ERROR: "ERROR",
        CRITICAL: "CRITICAL",
    }

    def __init__(self, main_engine: MainEngine, event_engine: EventEngine) -> None:
        super().__init__(main_engine, event_engine, "recorder")
        self.logger = DummyRunLogger()
        self.register_log(EVENT_LOG)

    def process_log_event(self, event: Event) -> None:
        """Process log event"""

        log: LogData = event.data
        level: str | int = self.level_map.get(log.level, log.level)
        self.logger.log(level, f"{log.gateway_name}: {log.msg}")

    def register_log(self, event_type: str) -> None:
        """Register log event handler"""
        self.event_engine.register(event_type, self.process_log_event)
