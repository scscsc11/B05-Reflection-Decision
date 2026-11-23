# PROCESSOR_SUPPORT_REPORT —— 处理器运行支撑接口约定

> **版本**：v0.1（骨架阶段，待王浩然/舒超/邓咏慷三方确认）
> **模块位置**：`dev/src/processor_runtime.py`
> **负责人**：邓咏慷（只负责本文件；核心算法由王浩然负责 `dev/src/processor.py`）
> **最后更新**：2026-11-23

---

## 1. 模块定位（做什么 / 不做什么）

### ✅ 做什么

`processor_runtime.py` 提供四件**与红蓝对抗领域完全无关**的通用工程能力：

| 能力 | 组件 | 典型用途 |
|---|---|---|
| 高精度阶段计时 | `Stopwatch` | 记录单次 `process()` 总耗时、每次反思 iteration 的分阶段耗时 |
| 时间预算状态 | `TimeBudget` | 告诉 processor 还剩多少时间，让它自行决定要不要提前停止反思 |
| 结构化 JSON 日志 | `StructuredLogger` | 每条日志一行独立 JSON，方便反思评分/实验汇总解析 |
| 配置读取与校验 | `ConfigLoader` | 从 env / json 文件 / dict 读配置，做类型检查 + 默认值管理 |

这四件事**全部使用 Python 标准库**（time / json / os / dataclasses / typing / contextlib），不引入任何第三方依赖。

### ❌ 明确不做什么

邓咏慷**不会**在 `processor_runtime.py` 里写任何以下逻辑：

- 不解析 scene["P"] / scene["v"] 的物理含义
- 不做任何决策求解 / 反思 / 进化 / 知识检索
- 不猜测 `process(scene, mode)` 里 `mode` 的枚举值
- 不猜测输出 `list[int]` 的长度、范围、语义
- 不自行定义或修改算法目标、约束、决策规则
- 不读写 `/input` 或 `/output`（IO 统一走 `scene_io.py`）

**任何上述逻辑都属于王浩然的 `processor.py` 或舒超的 `reflection.py` / `experience_store.py`**。

---

## 2. 公开 API 清单

### 2.1 `Stopwatch` —— 高精度计时

```python
sw = Stopwatch()
sw.start()                   # 开始计时
sw.lap("reflection_iter_1")  # 在当前时刻打一个命名 lap
sw.elapsed()                 # -> float, 秒
sw.elapsed_ms()              # -> int, 毫秒
sw.stop()                    # 停止计时
sw.reset()                   # 清空所有状态
sw.laps                      # -> List[Dict], 所有 lap 记录的只读副本
```

也可以用上下文管理器：
```python
with sw.measure("solve"):
    # 这里的代码耗时会自动被 start/stop 包起来
    ...
```

### 2.2 `TimeBudget` —— 时间预算

```python
budget = TimeBudget(total_seconds=30.0, stopwatch=sw)  # 30 秒预算
status = budget.checkpoint()
# status.is_exhausted  -> bool，是否已用完
# status.used_ratio    -> float, 0.0~1.0，已用比例
budget.resize(15.0)  # 运行中重新分配预算
```

**设计约定**：`checkpoint()` 只返回状态、不中断任何执行。processor.py 自己判断要不要停。

### 2.3 `StructuredLogger` —— JSON 行日志

```python
log = StructuredLogger(output_path="/path/to/runtime.log", scene_id="scene1_0_50_20")
log.info("reflection_start", phase="reflection", iter=1, budget_used=0.35)
log.warn("budget_low", phase="checkpoint", remaining_ms=2000)
log.error("solve_failed", phase="solve", exc=SomeError("..."))
log.close()
```

**文件路径为 None 时**：只输出到 stdout。

### 2.4 `ConfigLoader` —— 配置读取

```python
cfg = ConfigLoader(override_dict={"max_reflection_rounds": 5}, config_path="/path/to/config.json")
cfg.get("total_budget_seconds")  # float or None
cfg.all                          # -> Dict, 全量配置快照
cfg.warnings                     # -> List[str], 类型不匹配等 warning
```

**默认配置清单**（processor_runtime 自带安全回退，不是最终算法参数）：

| key | 默认值 | 期望类型 | 备注 |
|---|---|---|---|
| `total_budget_seconds` | `None` | `None \| float` | None = 无预算上限 |
| `log_path` | `None` | `None \| str` | None = 只 stdout |
| `scene_id` | `"unknown_scene"` | `str` | 用于日志 |
| `max_reflection_rounds` | `3` | `int` | 反思最大轮次 |
| `seed` | `42` | `int` | 可复现性 |

**优先级**：环境变量（前缀 `B05_RT_`）> `override_dict` > `config_path` 文件 > 默认值。

### 2.5 `RunContext` —— 聚合入口（processor.py 唯一需要 import 的对象）

```python
ctx = RunContext(
    config={"max_reflection_rounds": 5},   # 可选：从 dict 传
    config_path="/path/to/config.json",     # 可选：从文件传
)
ctx.sw       # Stopwatch
ctx.budget   # TimeBudget
ctx.log      # StructuredLogger
ctx.config   # ConfigLoader
ctx.budget_ok()             # -> bool, 预算还没用完
ctx.snapshot()              # -> Dict, 完整运行状态快照
ctx.close()                 # 收尾
```

### 2.6 `trace_process` 装饰器（可选）

```python
@trace_process
def process(scene, mode, ctx: RunContext):
    # 装饰器自动：记录入口/出口/耗时/预算/异常
    ...
```

---

## 3. 与 `processor.py` 的协作约定

### 3.1 RunContext 的传递方式（三方待确认）

**方案 A（推荐）**：processor.py 签名显式接收 RunContext
```python
def process(scene: dict, mode: str, ctx: RunContext) -> list[int]:
    ...
```

**方案 B**：RunContext 由 processor.py 自己创建（不暴露到签名）
```python
def process(scene: dict, mode: str) -> list[int]:
    ctx = RunContext()
    ...
```

### 3.2 processor.py 对 ctx 的使用禁区

- 不得修改 `ctx.sw` / `ctx.budget` / `ctx.log` / `ctx.config` 的内部私有属性
- 不得假设 ctx 存在就跳过自己的异常处理（RunContext 的 `log.error()` 只记录不吞异常）
- 不得把 ctx 序列化（它不是数据类）

### 3.3 接口变更流程

1. 在本文件第 2 节加上新方法签名 + 语义说明
2. 邓咏慷在 `processor_runtime.py` 里实现
3. 实现跑通后王浩然再在 `processor.py` 里引用
4. **禁止**直接在 `processor.py` 里临时 monkey-patch RunContext

---

## 4. 日志格式规范

每条日志一行独立 JSON。固定字段 **5 个**，调用方可追加任意字段。

### 4.1 固定字段（每条必有）

| 字段 | 类型 | 含义 |
|---|---|---|
| `timestamp_iso` | `str` | ISO 格式时间戳 |
| `level` | `"INFO" \| "WARN" \| "ERROR"` | 日志级别 |
| `event` | `str` | 事件名 |
| `phase` | `str` | 阶段标记（bootstrap / reflection / solve / exit） |
| `scene_id` | `str` | 场景标识 |

### 4.2 可选字段

| 字段 | 类型 | 典型场景 |
|---|---|---|
| `elapsed_ms` | `int` | 阶段耗时 |
| `budget_used_ratio` | `float` | checkpoint 预算消耗比例 |
| `remaining_ms` | `int` | 预算剩余 |
| `iter` | `int` | 反思轮次序号 |
| `result_type` | `str` | 出口返回值类型名 |
| `exc_type` / `exc_msg` | `str` | ERROR 级别异常信息 |

### 4.3 禁止的做法

- 不得在一条日志里塞整个 `scene`（P + v 会导致日志爆炸）
- 不得让一条 JSON 跨多行
- 不得混用 print 与 StructuredLogger

---

## 5. 时间预算传递约定

| 环节 | 负责方 | 怎么做 |
|---|---|---|
| 预算来源 | 邓咏慷 | ConfigLoader 读 env / file / dict |
| 预算检查 | 王浩然 | `ctx.budget_ok()` 或 `ctx.budget.checkpoint().is_exhausted` |
| 预算调整 | 王浩然 | `ctx.budget.resize(new_total)` |
| 预算耗尽处理 | 王浩然 | processor.py 自己决定；RunContext 只记录不中断 |

---

## 6. 异常处理约定

RunContext **从不吞异常**。`log.error()` 只记录，然后 `raise` 继续向上抛。

| 抛出方 | 异常类型 | 接住方 |
|---|---|---|
| processor_runtime 自己 | `ValueError` | processor.py 或 main.py |
| processor.py | 任意业务异常 | main.py / scene_io.py |

---

## 7. 待三方确认项（**必须先确认再写 processor.py / reflection.py**）

| 编号 | 问题 | 谁来答 |
|---|---|---|
| **C1** | `mode` 参数有哪些枚举值？含义？ | 舒超（接口契约） |
| **C2** | 输出 `list[int]` 长度 / 范围 / 语义？ | 舒超 |
| **C3** | scene JSON 是否只有 P + v 两个字段？ | 舒超（自测场景已核实是） |
| **C4** | RunContext 要不要显式放进 process 签名？（方案 A vs B） | 三方协商 |
| **C5** | max_reflection_rounds 默认值 3 合适吗？ | 王浩然 |
| **C6** | 正式评测预算 env 会注入吗？ | 舒超 / 官方 |

---

## 8. 本地验证

```bash
py -3 -c "
import sys; sys.path.insert(0, 'dev/src')
import processor_runtime as rt
ctx = rt.RunContext()
ctx.sw.start(); ctx.sw.lap('test'); ctx.sw.stop()
print('RunContext OK, elapsed_ms:', ctx.sw.elapsed_ms())
ctx.close()
"
```

---

## 9. 待办

| 项 | 负责人 | 状态 |
|---|---|---|
| processor_runtime.py 骨架 | 邓咏慷 | ✅ 已推 fork |
| PROCESSOR_SUPPORT_REPORT.md | 邓咏慷 | ✅ 已推 fork |
| processor_test_fixtures.py | 邓咏慷 | 待 C1~C3 确认 |
| test_processor_contract.py | 邓咏慷 | 待 C1~C4 确认 |
| test_processor_runtime.py | 邓咏慷 | 本 PR 合并后写 |
| processor.py 核心求解 | 王浩然 | 不在本 PR |
