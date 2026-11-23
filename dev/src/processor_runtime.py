#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""processor_runtime.py —— 处理器通用运行支撑模块。

本模块不包含任何红蓝对抗领域逻辑或决策求解算法。
它只提供运行计时、时间预算、结构化日志、配置读取这四件通用工程能力，
由 processor.py（王浩然负责）调用，双方通过 RunContext 这一入口对象协作。

依赖：全部使用 Python 标准库（time / json / os / dataclasses / typing / contextlib）。
不得新增第三方依赖，也不得修改本模块来配合算法目标变更。
"""

from __future__ import annotations

import json
import os
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Iterable, List, Optional

class Stopwatch:
    """使用 time.perf_counter() 的高精度计时器。支持 named lap 拆阶段。"""

    def __init__(self) -> None:
        self._t0: Optional[float] = None
        self._t1: Optional[float] = None
        self._laps: List[Dict[str, Any]] = []
        self._running: bool = False

    def start(self) -> None:
        self._t0 = time.perf_counter()
        self._running = True

    def stop(self) -> None:
        if self._running and self._t0 is not None:
            self._t1 = time.perf_counter()
            self._running = False

    def reset(self) -> None:
        self._t0 = self._t1 = None
        self._running = False
        self._laps.clear()

    def elapsed(self) -> float:
        if self._t0 is None:
            return 0.0
        if self._running:
            return time.perf_counter() - self._t0
        if self._t1 is not None:
            return self._t1 - self._t0
        return 0.0

    def elapsed_ms(self) -> int:
        return int(self.elapsed() * 1000)

    @property
    def is_running(self) -> bool:
        return self._running

    def lap(self, name: str) -> None:
        self._laps.append({
            "name": str(name),
            "elapsed_ms": self.elapsed_ms(),
            "t_stamp": time.monotonic(),
        })

    @property
    def laps(self) -> List[Dict[str, Any]]:
        return list(self._laps)

    @contextmanager
    def measure(self, lap_name: Optional[str] = None):
        self.start()
        try:
            yield self
        finally:
            self.stop()
            if lap_name is not None:
                self.lap(lap_name)


@dataclass
class BudgetStatus:
    """TimeBudget.checkpoint() 返回的快照。"""
    total_seconds: Optional[float]
    used_seconds: float
    remaining_seconds: Optional[float]
    used_ratio: Optional[float]
    is_exhausted: bool


class TimeBudget:
    """跟踪总预算 + 已用时间。checkpoint() 只报告、不中断。"""

    def __init__(self, total_seconds: Optional[float], stopwatch: Stopwatch) -> None:
        if total_seconds is not None and total_seconds <= 0:
            raise ValueError(f"total_seconds 必须为正数或 None，收到 {total_seconds!r}")
        self._total = total_seconds
        self._sw = stopwatch

    def checkpoint(self) -> BudgetStatus:
        used = self._sw.elapsed()
        if self._total is None:
            return BudgetStatus(None, used, None, None, False)
        remaining = self._total - used
        ratio = min(used / self._total, 1.0)
        return BudgetStatus(
            self._total, used, max(remaining, 0.0),
            ratio, remaining <= 0.0,
        )

    def resize(self, new_total: Optional[float]) -> None:
        if new_total is not None and new_total <= 0:
            raise ValueError(f"new_total 必须为正数或 None，收到 {new_total!r}")
        self._total = new_total

    @property
    def total_seconds(self) -> Optional[float]:
        return self._total


class StructuredLogger:
    """每条日志一行独立 JSON。固定字段：timestamp_iso / level / event / phase / scene_id。"""

    def __init__(self, output_path: Optional[str] = None, scene_id: str = "unknown_scene") -> None:
        self._path = output_path
        self._scene_id = str(scene_id)
        self._file_handle = None
        if self._path is not None:
            self._file_handle = open(self._path, "a", encoding="utf-8")

    def close(self) -> None:
        if self._file_handle is not None:
            self._file_handle.close()
            self._file_handle = None

    def _write(self, payload: Dict[str, Any]) -> None:
        line = json.dumps(payload, ensure_ascii=False, sort_keys=False)
        print(line, flush=True)
        if self._file_handle is not None:
            self._file_handle.write(line + "\n")
            self._file_handle.flush()

    def _emit(self, level: str, event: str, phase: str, **kwargs: Any) -> None:
        payload: Dict[str, Any] = {
            "timestamp_iso": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "level": level,
            "event": str(event),
            "phase": str(phase),
            "scene_id": self._scene_id,
        }
        payload.update(kwargs)
        self._write(payload)

    def info(self, event: str, phase: str = "-", **kwargs: Any) -> None:
        self._emit("INFO", event, phase, **kwargs)

    def warn(self, event: str, phase: str = "-", **kwargs: Any) -> None:
        self._emit("WARN", event, phase, **kwargs)

    def error(self, event: str, phase: str = "-", exc: Optional[BaseException] = None, **kwargs: Any) -> None:
        extra: Dict[str, Any] = {}
        if exc is not None:
            extra["exc_type"] = type(exc).__name__
            extra["exc_msg"] = str(exc)
        extra.update(kwargs)
        self._emit("ERROR", event, phase, **extra)


DEFAULT_CONFIG: Dict[str, Any] = {
    "total_budget_seconds": None,
    "log_path": None,
    "scene_id": "unknown_scene",
    "max_reflection_rounds": 3,
    "seed": 42,
}

CONFIG_TYPE_MAP: Dict[str, Any] = {
    "total_budget_seconds": (type(None), float),
    "log_path": (type(None), str),
    "scene_id": str,
    "max_reflection_rounds": int,
    "seed": int,
}


class ConfigLoader:
    """按 env > file > override_dict > default 优先级加载配置。"""

    ENV_PREFIX = "B05_RT_"

    def __init__(self, override_dict: Optional[Dict[str, Any]] = None, config_path: Optional[str] = None) -> None:
        self._values: Dict[str, Any] = {}
        self._warnings: List[str] = []
        self._load(override_dict, config_path)

    def _load(self, override_dict: Optional[Dict[str, Any]], config_path: Optional[str]) -> None:
        merged = dict(DEFAULT_CONFIG)
        if config_path is not None and os.path.isfile(config_path):
            try:
                with open(config_path, "r", encoding="utf-8") as f:
                    file_cfg = json.load(f)
                if isinstance(file_cfg, dict):
                    merged.update(file_cfg)
            except (OSError, json.JSONDecodeError) as exc:
                self._warnings.append(f"读取 config_path {config_path} 失败: {exc}")
        if override_dict:
            merged.update(override_dict)
        for key, expected_types in CONFIG_TYPE_MAP.items():
            env_key = self.ENV_PREFIX + key.upper()
            raw = os.environ.get(env_key)
            if raw is None:
                continue
            converted = self._try_convert(raw, expected_types)
            if converted is not None:
                merged[key] = converted
        for key, expected in CONFIG_TYPE_MAP.items():
            if key in merged and not isinstance(merged[key], expected if isinstance(expected, tuple) else (expected,)):
                self._warnings.append(f"配置键 {key} 类型不匹配")
        self._values = merged

    @staticmethod
    def _try_convert(raw: str, expected_types: Any) -> Optional[Any]:
        candidates: List[Any] = []
        if isinstance(expected_types, tuple):
            for t in expected_types:
                if t is type(None):
                    candidates.append(lambda s: None if s.lower() in ("none", "null", "") else None)
                else:
                    candidates.append(t)
        else:
            candidates.append(expected_types)
        for t in candidates:
            try:
                val = t(raw)
                if val is not None:
                    return val
            except (ValueError, TypeError):
                continue
        return None

    def get(self, key: str, default: Any = None) -> Any:
        return self._values.get(key, default)

    @property
    def all(self) -> Dict[str, Any]:
        return dict(self._values)

    @property
    def warnings(self) -> List[str]:
        return list(self._warnings)


class RunContext:
    """processor.py 唯一需要 import 的聚合入口。聚合 Stopwatch / TimeBudget / StructuredLogger / ConfigLoader。"""

    def __init__(self, config: Optional[Dict[str, Any]] = None, config_path: Optional[str] = None) -> None:
        self.config = ConfigLoader(override_dict=config, config_path=config_path)
        self.sw = Stopwatch()
        self.budget = TimeBudget(
            total_seconds=self.config.get("total_budget_seconds"),
            stopwatch=self.sw,
        )
        self.log = StructuredLogger(
            output_path=self.config.get("log_path"),
            scene_id=self.config.get("scene_id", "unknown_scene"),
        )
        self.log.info("run_context_init", phase="bootstrap", config_snapshot=self.config.all, warnings=self.config.warnings)

    def budget_ok(self) -> bool:
        status = self.budget.checkpoint()
        if status.is_exhausted:
            self.log.warn("budget_exhausted", phase="checkpoint", remaining_ms=int((status.remaining_seconds or 0) * 1000))
        return not status.is_exhausted

    def snapshot(self) -> Dict[str, Any]:
        status = self.budget.checkpoint()
        return {
            "elapsed_ms": self.sw.elapsed_ms(),
            "budget": {
                "total_seconds": status.total_seconds,
                "used_ratio": status.used_ratio,
                "remaining_seconds": status.remaining_seconds,
                "is_exhausted": status.is_exhausted,
            },
            "laps": self.sw.laps,
            "config": self.config.all,
        }

    def close(self) -> None:
        self.log.info("run_context_close", phase="teardown", final_elapsed_ms=self.sw.elapsed_ms())
        self.log.close()


def trace_process(func: Callable[..., Any], ctx_attr: str = "ctx") -> Callable[..., Any]:
    """可选装饰器：自动在 process() 入口/出口打日志、记录耗时、落异常 ERROR 日志。"""
    import functools
    import inspect

    @functools.wraps(func)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        ctx: Optional[RunContext] = None
        if ctx_attr in kwargs and isinstance(kwargs[ctx_attr], RunContext):
            ctx = kwargs[ctx_attr]
        else:
            params = list(inspect.signature(func).parameters.keys())
            try:
                idx = params.index(ctx_attr)
                if idx < len(args) and isinstance(args[idx], RunContext):
                    ctx = args[idx]
            except ValueError:
                pass
        if ctx is None:
            return func(*args, **kwargs)
        ctx.sw.start()
        ctx.log.info("process_enter", phase="entry")
        try:
            result = func(*args, **kwargs)
            ctx.sw.stop()
            ctx.log.info(
                "process_exit", phase="exit",
                elapsed_ms=ctx.sw.elapsed_ms(),
                result_type=type(result).__name__,
                budget_used_ratio=ctx.budget.checkpoint().used_ratio,
            )
            return result
        except BaseException as exc:
            ctx.sw.stop()
            ctx.log.error("process_exception", phase="exception", exc=exc, elapsed_ms=ctx.sw.elapsed_ms())
            raise

    return wrapper


__all__ = [
    "Stopwatch", "TimeBudget", "BudgetStatus", "StructuredLogger",
    "ConfigLoader", "RunContext", "trace_process", "DEFAULT_CONFIG",
]
