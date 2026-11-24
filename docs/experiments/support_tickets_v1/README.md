# 民用工单盲测

工单来自合成校园服务场景。种子集有 8 例，留出集有 24 例，四类各 6 例。两套工单的案例 ID 互不重叠。案例如经修改，需另立版本并更新清单和参考标签。

- `seed_input/` 保存可带参考反馈的种子工单和种子答案。
- `heldout_input/` 只保存留出工单。初判和三组复核共用该目录。
- `offline/` 保存留出答案、参考标签的判定依据和复标记录。留出答案由独立评分进程读取。

[数据清单](manifest.json)记录输入的 SHA-256。分组使用同一份冻结初判，复核上限为 2 轮，模型调用预算为每次阶段运行 600 秒。评分器按案例 ID 核对样本和初判指纹。

## 本地验证

在仓库根目录预览命令。此操作可以在配置模型网关前执行。

```bash
python3 -B docs/experiments/support_tickets_v1/run_stage.py guarded /tmp/b05-preview --dry-run
python3 -B docs/experiments/support_tickets_v1/run_stage.py score /tmp/b05-preview --dry-run
```

知识、反思和评分的进程内替身测试在 `dev` 目录运行。

```bash
python3 -B -m unittest -v tests.test_knowledge tests.test_reflection_live tests.test_team_integration
```

## 分组运行与离线评分

在获准使用模型网关的环境中，由运行环境提供模型配置。进入仓库根目录，按顺序运行各阶段。

```bash
(
    set -e
    bundle=docs/experiments/support_tickets_v1
    mkdir -p tmp
    run_dir=$(mktemp -d "$PWD/tmp/blind_support_tickets_v1_XXXXXXXX")
    printf 'Run directory: %s\n' "$run_dir"
    for stage in seed initial without_history with_history guarded score; do
        python3 -B "$bundle/run_stage.py" "$stage" "$run_dir"
    done
    python3 -B "$bundle/request_cost.py" "$run_dir"
)
```

阶段中断后，用原运行目录和同一阶段参数继续。已完成案例从断点恢复，模型调用预算按本次启动计算。保留每次启动的 `invocation_logs/` 日志，汇总所有尝试和已观测耗时。中止时缺失的结束记录列为耗时未知。

`offline_score.json` 用于比较准确率、改对、改错、持平。`request_cost.json` 汇总各阶段的实际尝试，并逐条核对进入发布结果的调用记录。结果解释和知识匹配规则见[反思与知识记录](../../reflection_knowledge/REFLECTION_KNOWLEDGE.md)。
