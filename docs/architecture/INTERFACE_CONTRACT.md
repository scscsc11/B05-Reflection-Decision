# 软件接口契约

## 入口和路径

容器入口为 `dev/run.sh`，脚本将参数交给 `dev/src/main.py`。`DATA_ROOT` 指定输入目录，默认 `/input`。输出目录优先取 `--out-dir`，其次取 `OUTPUT_DIR`，默认 `/output`。写出任务使用输入目录之外的空目录。

`--task support-tickets` 进入民用工单流程。结构校验用 `--validate-only`，固定值写出用 `--fixture`，两者互斥，供场景文件接口检查使用。`--test` 将测试调用标记写入日志。`--fixture` 和 `--validate-only` 均省略时，场景批次走正式处理入口。

## 场景文件与处理器

`scene_io.load_scenes` 按文件名排序读取输入目录顶层的 `.json` 文件。文件名采用 `scene<S>_<I>_<N>_<M>.json`，其中 `S` 为 1 或 2，`I` 为 0 至 4，`N` 和 `M` 为正整数。每个文件是 UTF-8 编码的 JSON 对象，`P` 为 `N` 行 `M` 列的数组，`v` 为 `M` 项的数组。数组项须为有限数值，布尔值不属于合法数值。解析器拒绝重复键，允许保留其他字段。

主程序从 `dev/src/processor.py` 装载 `process`，每个场景依次传入 `norethink` 和 `rethink`。`Scene` 包含文件名 `name`、行数 `rows`、列数 `columns` 和原始对象 `data`。处理器按只读方式使用 `Scene`，输入校验和结果写出由主程序负责。

```python
def process(scene: Scene, mode: str) -> list[int]:
    ...
```

返回值是长度为 `scene.rows` 的整数列表。主程序校验类型和长度，复制返回列表，并按输入文件名写至对应的 `norethink/` 和 `rethink/` 目录。结果对象仅含 `results` 字段。索引含义及取值范围在正式模块联调时按评测要求检查。固定值路径为两种模式写入相同形状的占位结果，用于验收目录与文件结构。

| **退出码** | **触发条件** |
| --- | --- |
| `0` | 校验通过，或请求的结果已发布。 |
| `1` | 输入、模型调用或发布失败，或处理器装载、执行或返回值校验失败。单例调用或返回值校验失败时，日志包含场景名及模式。 |
| `2` | 命令行参数解析失败。 |
| `3` | 正式入口缺少 `dev/src/processor.py`。 |

场景批次在全部输入通过校验后调用处理器。全部返回值校验通过后才开始发布。发布阶段先在输出目录内暂存结果，随后发布两个模式目录。有可写知识库时，在两目录发布后提交事务。发布或提交抛出异常时，已移动的模式目录按逆序移回暂存区。

## 民用工单与模型客户端

`benchmark.json` 顶层含 `domain`、`labels` 和 `cases`。`labels` 是类别名到说明的映射，至少有两类。案例含唯一 `id`、`topic` 和 `text`，可附 `features` 字符串数组。有反馈的种子运行使用同目录 `answers.json`，其内容为案例编号到参考标签的映射。

反思模块通过以下方法调用模型。`stage` 为 `initial` 或 `review`，`instructions` 为当前阶段的指令，`data` 为案例、标签定义和阶段上下文，`schema` 约束返回对象。`budget` 单位为秒，表示本次调用可用的剩余时间。

```python
def complete(stage: str, instructions: str, data: dict, schema: dict, *, budget: float | None = None) -> dict:
    ...
```

初判只返回 `label` 和 `reason`。复核只返回 `label`、`review` 和 `knowledge`。`knowledge` 含 `problem`、`lesson` 和 `applies_when`。`label` 须为当前类别之一，其余文本字段去除首尾空白后须非空。复核上下文包含初判、上一轮判断和已筛选经验。有反馈运行向模型提供正确性与已排除类别。盲测的反馈记录为空。

客户端从环境读取 `LLM_BASE_URL`、`LLM_MODEL` 和 `LLM_API_KEY`，请求路径在基地址后接 `/chat/completions`。`LLM_TIMEOUT_SECONDS` 默认为 `120`，单次请求采用超时与剩余预算的较小值。`LLM_USE_JSON_SCHEMA=1` 启用结构化响应格式。网关连接错误、超时或响应不可解析时抛出 `ModelError`。反思模块仅在有 `retry_after` 且预算允许时重试一次。凭据由获授权环境注入，运行证据记录模型身份与请求成本。

| **工单参数** | **约束** |
| --- | --- |
| `--review-rounds`、`--time-budget` | 复核上限为 0 至 5，默认 2。预算默认 180 秒，须为正的有限数，每次启动重新计时。 |
| `--blind`、`--initial-results` | 盲态初判使用 `--review-rounds 0`。盲态复核使用同一案例和同一模型配置的冻结初判。留出答案交离线评分器。 |
| `--knowledge-db`、`--no-history` | 带反馈的复核使用可写库。启用历史的盲态复核以只读方式打开与留出案例分离的种子库。`--no-history` 跳过检索。 |
| `--guard-review` | 用于启用历史的盲态复核。使用条件精确匹配且来源标签已验证的记录。只有这些记录支持同一类别且该类别不同于初判时才启动复核。 |
| `--guard-require-request-feature` | 与 `--guard-review` 联用。条件完全匹配时另核对是否恰有一个格式为 `request:<动作>` 的主诉特征。结果记录匹配策略，断点校验包含该策略。 |
| `--checkpoint` | 每例完成后写断点。继续同一运行时复用输入、模型配置、知识状态和断点。断点与数据库分别放在输入目录和结果目录之外。 |
| `--simulated-gateway` | 用于本地脚本化网关。进程内替身通过 `reflection.run(..., in_process_model=...)` 注入，具有独立的来源标记。 |

工单初判发布至 `norethink/benchmark_results.json`。启用复核时另写 `rethink/benchmark_results.json`，逐例保留复核轮次、改判、停止原因和实际发送的经验。有反馈的经验修订保存来源候选及最终所选轮次，标签验证状态对应来源案例。离线评分器以冻结初判、各复核组结果和独立答案为输入，可通过 `--answers-sha256` 校验答案文件。各复核组须使用同一留出集、初判、轮数上限和调用预算。

本地验收命令和分工见[集成验收清单](../integration/INTEGRATION_CHECKLIST.md)。
