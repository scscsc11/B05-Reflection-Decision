# 场景包材料清单与一致性检查

> 负责人：马子越（分支 `task/ug2-scenario-evidence`）
> 职责边界：舒超确认场景内容后做规范化整理；发现数据与报告不一致时列出差异交舒超，不自行改变场景核心设定。

## 1. 材料清单

舒超确认的冻结数据为两个实验包的输入与答案文件（提交 `4cb3fbf`、`e4cf792`，日期 2026-11-23）。版本细节见各自 `manifest.json`。检查口径见 `docs/scenario/SCENARIO_DESIGN.md`。

| 文件名（相对仓库根） | 用途 | 报告章节 | 版本日期 | 确认状态 | 备注 |
| --- | --- | --- | --- | --- | --- |
| docs/experiments/support_tickets_v1/seed_input/benchmark.json | 民用工单种子输入（8 例） | 第3章 数据划分 / 第5章 实验设置 | 2026-11-23 | 已确认 | 4cb3fbf |
| docs/experiments/support_tickets_v1/seed_input/answers.json | 种子标签映射（8 条） | 第3章 数据划分 | 2026-11-23 | 已确认 | 4cb3fbf |
| docs/experiments/support_tickets_v1/heldout_input/benchmark.json | 留出工单输入（24 例，四类各 6） | 第3章 / 第5章 | 2026-11-23 | 已确认 | 4cb3fbf |
| docs/experiments/support_tickets_v1/offline/answers.json | 留出参考答案（24 条） | 第5章 离线评分 | 2026-11-23 | 已确认 | 4cb3fbf |
| docs/experiments/support_tickets_v1/offline/label_rationales.json | 标签依据，供复核 | 第3章 标签依据 | 2026-11-23 | 已确认 | 4cb3fbf |
| docs/experiments/request_guard_v1/seed_input/benchmark.json | 主诉对照种子输入（5 例） | 第5章 条件复核对照 | 2026-11-23 | 已确认 | e4cf792 |
| docs/experiments/request_guard_v1/seed_input/answers.json | 主诉对照种子标签（5 条） | 第5章 条件复核对照 | 2026-11-23 | 已确认 | e4cf792 |
| docs/experiments/request_guard_v1/heldout_input/benchmark.json | 主诉对照留出输入（7 例） | 第5章 条件复核对照 | 2026-11-23 | 已确认 | e4cf792 |
| docs/experiments/request_guard_v1/offline/answers.json | 主诉对照参考答案（7 条） | 第5章 条件复核对照 | 2026-11-23 | 已确认 | e4cf792 |
| docs/experiments/request_guard_v1/offline/scenarios.json | 主诉对照参考场景 | 第5章 条件复核对照 | 2026-11-23 | 已确认 | e4cf792 |

字段说明：
- **用途**：该文件在评测/报告中的作用（如主场景定义、天气配置、实体参数）。
- **报告章节**：报告中引用该文件的位置（如第3章、第5章实验设置）。
- **版本日期**：舒超确认该版本的日期，格式 `YYYY-MM-DD`。
- **确认状态**：`待确认` / `已确认` / `已作废`。

## 2. 一致性检查

检查脚本：`dev/tests/check_scenario_package.py`，清单：`data/team_scenario/manifest.json`。

运行命令：

```bash
python dev/tests/check_scenario_package.py \
  --root . \
  --manifest data/team_scenario/manifest.json \
  --out docs/scenario/SCENARIO_PACKAGE_CHECK.md
```

（清单中的路径相对仓库根，故 `--root .`。）

检查项：文件存在性、JSON 可解析性、必需字段、字段类型、矩阵/向量维度、有限数值（NaN/Inf）、报告引用文件是否存在。仅做格式与一致性检查，不生成专用决策数据。

以下区间由脚本自动更新，请勿手动编辑：

<!-- AUTO_CHECK_START -->

## 自动检查结果

| 文件 | 用途 | 报告章节 | 版本日期 | 确认状态 | 检查项 | 结果 | 说明 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| docs/experiments/support_tickets_v1/seed_input/benchmark.json | 民用工单种子输入（8 例），用于构建知识种子 | 第3章 数据划分 / 第5章 实验设置 | 2026-11-23 | 已确认 | 文件存在 | PASS | docs/experiments/support_tickets_v1/seed_input/benchmark.json |
| docs/experiments/support_tickets_v1/seed_input/benchmark.json | 民用工单种子输入（8 例），用于构建知识种子 | 第3章 数据划分 / 第5章 实验设置 | 2026-11-23 | 已确认 | JSON 可解析 | PASS | parse_constant 已启用 |
| docs/experiments/support_tickets_v1/seed_input/benchmark.json | 民用工单种子输入（8 例），用于构建知识种子 | 第3章 数据划分 / 第5章 实验设置 | 2026-11-23 | 已确认 | 必需字段 domain | PASS | 存在 |
| docs/experiments/support_tickets_v1/seed_input/benchmark.json | 民用工单种子输入（8 例），用于构建知识种子 | 第3章 数据划分 / 第5章 实验设置 | 2026-11-23 | 已确认 | 必需字段 labels | PASS | 存在 |
| docs/experiments/support_tickets_v1/seed_input/benchmark.json | 民用工单种子输入（8 例），用于构建知识种子 | 第3章 数据划分 / 第5章 实验设置 | 2026-11-23 | 已确认 | 必需字段 cases | PASS | 存在 |
| docs/experiments/support_tickets_v1/seed_input/benchmark.json | 民用工单种子输入（8 例），用于构建知识种子 | 第3章 数据划分 / 第5章 实验设置 | 2026-11-23 | 已确认 | 必需字段 cases.0.id | PASS | 存在 |
| docs/experiments/support_tickets_v1/seed_input/benchmark.json | 民用工单种子输入（8 例），用于构建知识种子 | 第3章 数据划分 / 第5章 实验设置 | 2026-11-23 | 已确认 | 必需字段 cases.0.topic | PASS | 存在 |
| docs/experiments/support_tickets_v1/seed_input/benchmark.json | 民用工单种子输入（8 例），用于构建知识种子 | 第3章 数据划分 / 第5章 实验设置 | 2026-11-23 | 已确认 | 必需字段 cases.0.text | PASS | 存在 |
| docs/experiments/support_tickets_v1/seed_input/benchmark.json | 民用工单种子输入（8 例），用于构建知识种子 | 第3章 数据划分 / 第5章 实验设置 | 2026-11-23 | 已确认 | 类型 domain | PASS | string |
| docs/experiments/support_tickets_v1/seed_input/benchmark.json | 民用工单种子输入（8 例），用于构建知识种子 | 第3章 数据划分 / 第5章 实验设置 | 2026-11-23 | 已确认 | 类型 labels | PASS | object |
| docs/experiments/support_tickets_v1/seed_input/benchmark.json | 民用工单种子输入（8 例），用于构建知识种子 | 第3章 数据划分 / 第5章 实验设置 | 2026-11-23 | 已确认 | 类型 cases | PASS | array |
| docs/experiments/support_tickets_v1/seed_input/benchmark.json | 民用工单种子输入（8 例），用于构建知识种子 | 第3章 数据划分 / 第5章 实验设置 | 2026-11-23 | 已确认 | 类型 cases.0.features | PASS | array |
| docs/experiments/support_tickets_v1/seed_input/benchmark.json | 民用工单种子输入（8 例），用于构建知识种子 | 第3章 数据划分 / 第5章 实验设置 | 2026-11-23 | 已确认 | 有限数值 | PASS | 无 NaN/Inf |
| docs/experiments/support_tickets_v1/seed_input/answers.json | 种子案例编号到类别的映射（8 条） | 第3章 数据划分 | 2026-11-23 | 已确认 | 文件存在 | PASS | docs/experiments/support_tickets_v1/seed_input/answers.json |
| docs/experiments/support_tickets_v1/seed_input/answers.json | 种子案例编号到类别的映射（8 条） | 第3章 数据划分 | 2026-11-23 | 已确认 | JSON 可解析 | PASS | parse_constant 已启用 |
| docs/experiments/support_tickets_v1/seed_input/answers.json | 种子案例编号到类别的映射（8 条） | 第3章 数据划分 | 2026-11-23 | 已确认 | 必需字段 r2-1b871f313273 | PASS | 存在 |
| docs/experiments/support_tickets_v1/seed_input/answers.json | 种子案例编号到类别的映射（8 条） | 第3章 数据划分 | 2026-11-23 | 已确认 | 有限数值 | PASS | 无 NaN/Inf |
| docs/experiments/support_tickets_v1/heldout_input/benchmark.json | 民用工单留出输入（24 例，四类各 6） | 第3章 数据划分 / 第5章 实验设置 | 2026-11-23 | 已确认 | 文件存在 | PASS | docs/experiments/support_tickets_v1/heldout_input/benchmark.json |
| docs/experiments/support_tickets_v1/heldout_input/benchmark.json | 民用工单留出输入（24 例，四类各 6） | 第3章 数据划分 / 第5章 实验设置 | 2026-11-23 | 已确认 | JSON 可解析 | PASS | parse_constant 已启用 |
| docs/experiments/support_tickets_v1/heldout_input/benchmark.json | 民用工单留出输入（24 例，四类各 6） | 第3章 数据划分 / 第5章 实验设置 | 2026-11-23 | 已确认 | 必需字段 domain | PASS | 存在 |
| docs/experiments/support_tickets_v1/heldout_input/benchmark.json | 民用工单留出输入（24 例，四类各 6） | 第3章 数据划分 / 第5章 实验设置 | 2026-11-23 | 已确认 | 必需字段 labels | PASS | 存在 |
| docs/experiments/support_tickets_v1/heldout_input/benchmark.json | 民用工单留出输入（24 例，四类各 6） | 第3章 数据划分 / 第5章 实验设置 | 2026-11-23 | 已确认 | 必需字段 cases | PASS | 存在 |
| docs/experiments/support_tickets_v1/heldout_input/benchmark.json | 民用工单留出输入（24 例，四类各 6） | 第3章 数据划分 / 第5章 实验设置 | 2026-11-23 | 已确认 | 类型 domain | PASS | string |
| docs/experiments/support_tickets_v1/heldout_input/benchmark.json | 民用工单留出输入（24 例，四类各 6） | 第3章 数据划分 / 第5章 实验设置 | 2026-11-23 | 已确认 | 类型 labels | PASS | object |
| docs/experiments/support_tickets_v1/heldout_input/benchmark.json | 民用工单留出输入（24 例，四类各 6） | 第3章 数据划分 / 第5章 实验设置 | 2026-11-23 | 已确认 | 类型 cases | PASS | array |
| docs/experiments/support_tickets_v1/heldout_input/benchmark.json | 民用工单留出输入（24 例，四类各 6） | 第3章 数据划分 / 第5章 实验设置 | 2026-11-23 | 已确认 | 有限数值 | PASS | 无 NaN/Inf |
| docs/experiments/support_tickets_v1/offline/answers.json | 留出案例参考标签（24 条），离线评分只读 | 第5章 离线评分 | 2026-11-23 | 已确认 | 文件存在 | PASS | docs/experiments/support_tickets_v1/offline/answers.json |
| docs/experiments/support_tickets_v1/offline/answers.json | 留出案例参考标签（24 条），离线评分只读 | 第5章 离线评分 | 2026-11-23 | 已确认 | JSON 可解析 | PASS | parse_constant 已启用 |
| docs/experiments/support_tickets_v1/offline/answers.json | 留出案例参考标签（24 条），离线评分只读 | 第5章 离线评分 | 2026-11-23 | 已确认 | 必需字段 r2-13e86ddef3c2 | PASS | 存在 |
| docs/experiments/support_tickets_v1/offline/answers.json | 留出案例参考标签（24 条），离线评分只读 | 第5章 离线评分 | 2026-11-23 | 已确认 | 有限数值 | PASS | 无 NaN/Inf |
| docs/experiments/support_tickets_v1/offline/label_rationales.json | 留出案例标签依据，供资料复核 | 第3章 标签依据 | 2026-11-23 | 已确认 | 文件存在 | PASS | docs/experiments/support_tickets_v1/offline/label_rationales.json |
| docs/experiments/support_tickets_v1/offline/label_rationales.json | 留出案例标签依据，供资料复核 | 第3章 标签依据 | 2026-11-23 | 已确认 | JSON 可解析 | PASS | parse_constant 已启用 |
| docs/experiments/support_tickets_v1/offline/label_rationales.json | 留出案例标签依据，供资料复核 | 第3章 标签依据 | 2026-11-23 | 已确认 | 有限数值 | PASS | 无 NaN/Inf |
| docs/experiments/request_guard_v1/seed_input/benchmark.json | 主诉对照种子输入（5 例） | 第5章 条件复核对照 | 2026-11-23 | 已确认 | 文件存在 | PASS | docs/experiments/request_guard_v1/seed_input/benchmark.json |
| docs/experiments/request_guard_v1/seed_input/benchmark.json | 主诉对照种子输入（5 例） | 第5章 条件复核对照 | 2026-11-23 | 已确认 | JSON 可解析 | PASS | parse_constant 已启用 |
| docs/experiments/request_guard_v1/seed_input/benchmark.json | 主诉对照种子输入（5 例） | 第5章 条件复核对照 | 2026-11-23 | 已确认 | 必需字段 domain | PASS | 存在 |
| docs/experiments/request_guard_v1/seed_input/benchmark.json | 主诉对照种子输入（5 例） | 第5章 条件复核对照 | 2026-11-23 | 已确认 | 必需字段 labels | PASS | 存在 |
| docs/experiments/request_guard_v1/seed_input/benchmark.json | 主诉对照种子输入（5 例） | 第5章 条件复核对照 | 2026-11-23 | 已确认 | 必需字段 cases | PASS | 存在 |
| docs/experiments/request_guard_v1/seed_input/benchmark.json | 主诉对照种子输入（5 例） | 第5章 条件复核对照 | 2026-11-23 | 已确认 | 必需字段 cases.0.id | PASS | 存在 |
| docs/experiments/request_guard_v1/seed_input/benchmark.json | 主诉对照种子输入（5 例） | 第5章 条件复核对照 | 2026-11-23 | 已确认 | 必需字段 cases.0.topic | PASS | 存在 |
| docs/experiments/request_guard_v1/seed_input/benchmark.json | 主诉对照种子输入（5 例） | 第5章 条件复核对照 | 2026-11-23 | 已确认 | 必需字段 cases.0.text | PASS | 存在 |
| docs/experiments/request_guard_v1/seed_input/benchmark.json | 主诉对照种子输入（5 例） | 第5章 条件复核对照 | 2026-11-23 | 已确认 | 类型 domain | PASS | string |
| docs/experiments/request_guard_v1/seed_input/benchmark.json | 主诉对照种子输入（5 例） | 第5章 条件复核对照 | 2026-11-23 | 已确认 | 类型 labels | PASS | object |
| docs/experiments/request_guard_v1/seed_input/benchmark.json | 主诉对照种子输入（5 例） | 第5章 条件复核对照 | 2026-11-23 | 已确认 | 类型 cases | PASS | array |
| docs/experiments/request_guard_v1/seed_input/benchmark.json | 主诉对照种子输入（5 例） | 第5章 条件复核对照 | 2026-11-23 | 已确认 | 类型 cases.0.features | PASS | array |
| docs/experiments/request_guard_v1/seed_input/benchmark.json | 主诉对照种子输入（5 例） | 第5章 条件复核对照 | 2026-11-23 | 已确认 | 有限数值 | PASS | 无 NaN/Inf |
| docs/experiments/request_guard_v1/seed_input/answers.json | 主诉对照种子标签（5 条） | 第5章 条件复核对照 | 2026-11-23 | 已确认 | 文件存在 | PASS | docs/experiments/request_guard_v1/seed_input/answers.json |
| docs/experiments/request_guard_v1/seed_input/answers.json | 主诉对照种子标签（5 条） | 第5章 条件复核对照 | 2026-11-23 | 已确认 | JSON 可解析 | PASS | parse_constant 已启用 |
| docs/experiments/request_guard_v1/seed_input/answers.json | 主诉对照种子标签（5 条） | 第5章 条件复核对照 | 2026-11-23 | 已确认 | 必需字段 req-s01 | PASS | 存在 |
| docs/experiments/request_guard_v1/seed_input/answers.json | 主诉对照种子标签（5 条） | 第5章 条件复核对照 | 2026-11-23 | 已确认 | 有限数值 | PASS | 无 NaN/Inf |
| docs/experiments/request_guard_v1/heldout_input/benchmark.json | 主诉对照留出输入（7 例） | 第5章 条件复核对照 | 2026-11-23 | 已确认 | 文件存在 | PASS | docs/experiments/request_guard_v1/heldout_input/benchmark.json |
| docs/experiments/request_guard_v1/heldout_input/benchmark.json | 主诉对照留出输入（7 例） | 第5章 条件复核对照 | 2026-11-23 | 已确认 | JSON 可解析 | PASS | parse_constant 已启用 |
| docs/experiments/request_guard_v1/heldout_input/benchmark.json | 主诉对照留出输入（7 例） | 第5章 条件复核对照 | 2026-11-23 | 已确认 | 必需字段 domain | PASS | 存在 |
| docs/experiments/request_guard_v1/heldout_input/benchmark.json | 主诉对照留出输入（7 例） | 第5章 条件复核对照 | 2026-11-23 | 已确认 | 必需字段 labels | PASS | 存在 |
| docs/experiments/request_guard_v1/heldout_input/benchmark.json | 主诉对照留出输入（7 例） | 第5章 条件复核对照 | 2026-11-23 | 已确认 | 必需字段 cases | PASS | 存在 |
| docs/experiments/request_guard_v1/heldout_input/benchmark.json | 主诉对照留出输入（7 例） | 第5章 条件复核对照 | 2026-11-23 | 已确认 | 类型 domain | PASS | string |
| docs/experiments/request_guard_v1/heldout_input/benchmark.json | 主诉对照留出输入（7 例） | 第5章 条件复核对照 | 2026-11-23 | 已确认 | 类型 labels | PASS | object |
| docs/experiments/request_guard_v1/heldout_input/benchmark.json | 主诉对照留出输入（7 例） | 第5章 条件复核对照 | 2026-11-23 | 已确认 | 类型 cases | PASS | array |
| docs/experiments/request_guard_v1/heldout_input/benchmark.json | 主诉对照留出输入（7 例） | 第5章 条件复核对照 | 2026-11-23 | 已确认 | 有限数值 | PASS | 无 NaN/Inf |
| docs/experiments/request_guard_v1/offline/answers.json | 主诉对照留出参考答案（7 条） | 第5章 条件复核对照 | 2026-11-23 | 已确认 | 文件存在 | PASS | docs/experiments/request_guard_v1/offline/answers.json |
| docs/experiments/request_guard_v1/offline/answers.json | 主诉对照留出参考答案（7 条） | 第5章 条件复核对照 | 2026-11-23 | 已确认 | JSON 可解析 | PASS | parse_constant 已启用 |
| docs/experiments/request_guard_v1/offline/answers.json | 主诉对照留出参考答案（7 条） | 第5章 条件复核对照 | 2026-11-23 | 已确认 | 必需字段 req-h01 | PASS | 存在 |
| docs/experiments/request_guard_v1/offline/answers.json | 主诉对照留出参考答案（7 条） | 第5章 条件复核对照 | 2026-11-23 | 已确认 | 有限数值 | PASS | 无 NaN/Inf |
| docs/experiments/request_guard_v1/offline/scenarios.json | 主诉对照参考场景，供条件复核读取 | 第5章 条件复核对照 | 2026-11-23 | 已确认 | 文件存在 | PASS | docs/experiments/request_guard_v1/offline/scenarios.json |
| docs/experiments/request_guard_v1/offline/scenarios.json | 主诉对照参考场景，供条件复核读取 | 第5章 条件复核对照 | 2026-11-23 | 已确认 | JSON 可解析 | PASS | parse_constant 已启用 |
| docs/experiments/request_guard_v1/offline/scenarios.json | 主诉对照参考场景，供条件复核读取 | 第5章 条件复核对照 | 2026-11-23 | 已确认 | 有限数值 | PASS | 无 NaN/Inf |

报告引用检查：报告引用 docs/scenario/SCENARIO_DESIGN.md — PASS — 存在
报告引用检查：报告引用 docs/experiments/support_tickets_v1/README.md — PASS — 存在
报告引用检查：报告引用 docs/experiments/request_guard_v1/README.md — PASS — 存在

<!-- AUTO_CHECK_END -->

## 3. 差异清单（交舒超处理）

发现数据与报告不一致时填写，不自行修改场景设定。

**差异 1（SHA-256 摘要，11 个文件全部不符）：** 两个实验包 `manifest.json` 的 `sha256` 字段记录的摘要，与当前仓库文件按代码口径 `hashlib.sha256(path.read_bytes()).hexdigest()` 实测值全部不一致；而清单与数据文件是同一提交写入（`4cb3fbf`、`e4cf792`，均为 2026-11-23），排除"数据后续被改动"的常见原因。这会导致 `dev/src/scene_io.read_json(expected_sha256=...)` 和 `run_stage.py`、`run_comparison.py` 在校验阶段直接拒绝输入。摘要只列前 16 位，完整值可用上面命令复算。

| 序号 | 文件（相对 docs/experiments/） | 清单记录（前16位） | 实测（前16位） |
| --- | --- | --- | --- |
| 1 | support_tickets_v1/heldout_input/benchmark.json | 2b742e1f308c066f | 330b0b68bb3f2f13 |
| 2 | support_tickets_v1/offline/answers.json | 736fa4ceb1597a77 | 0003c56330417b91 |
| 3 | support_tickets_v1/offline/label_rationales.json | 50b2473a4412ce3e | d8718a9d5afcdbc1 |
| 4 | support_tickets_v1/seed_input/answers.json | b31445919f5cb000 | ef8e64f503b9a22b |
| 5 | support_tickets_v1/seed_input/benchmark.json | 87af21c5df802873 | 241e7c003ad75892 |
| 6 | support_tickets_v1/offline/label_audit.json | 1a79d68b2511a5ed | db52864fbafb7c33 |
| 7 | request_guard_v1/seed_input/benchmark.json | 54f040e5b89fb4c7 | 3d0fbdf3cb4de71b |
| 8 | request_guard_v1/seed_input/answers.json | 53656254f5734fd3 | 2b7f3e40afb9f79c |
| 9 | request_guard_v1/heldout_input/benchmark.json | 35612f1123e3b8b1 | 2ee4ad7ae07caf1f |
| 10 | request_guard_v1/offline/answers.json | 1d87f94bb7e4da64 | 4bf932930aa3ffcc |
| 11 | request_guard_v1/offline/scenarios.json | 034033b19e034a45 | 4cdc561df586201e |

- **数据来源**：各实验包 `manifest.json` 的 `sha256` 字段 vs 当前工作树文件实测。
- **报告表述**：`SCENARIO_DESIGN.md` 要求"清单记录 SHA-256 摘要"，且代码据此校验输入。
- **处理建议**：交舒超核对——是清单摘要写错，还是数据文件应为摘要对应的版本。在此之前，本行只记录差异，不修改任何数据或清单，也不据此出具评测结论。
- **状态**：待舒超处理。

**差异 2（证据文件缺位）：** README 引用的结果文件 `offline_score.json`、`request_cost.json`、`comparison.json`、`invocation_logs/` 在仓库中均不存在（产出在 `tmp/` 运行目录，未纳入版本库）。已在 `EVIDENCE_INDEX.md` 标为"未开展"，不作为真实结果引用。状态：待实际运行产生。
