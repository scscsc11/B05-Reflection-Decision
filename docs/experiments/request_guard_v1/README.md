# 主诉特征的条件复核对照

对照使用 5 条合成种子工单和 7 条留出工单。两组使用同一份种子库、同一份冻结初判和相同的替身应答规则。既有条件复核检查已验证历史的条件是否完全匹配。加设主诉要求后，参与匹配的条件还须包含一个有效的 `request:` 特征。

主诉特征依据工单中的请求动作标注。例如，`request:confirm-location` 表示请求确认地点。缺少主诉标记或含多个标记时，启用主诉要求的条件复核跳过该例。

```bash
python3 -B docs/experiments/request_guard_v1/run_comparison.py tmp/knowledge_applicability_request_demo
```

从仓库根目录运行，输出目录每次另取新名。入口使用进程内替身。`comparison.json` 保存逐例配对结果、分组计数和参考答案读取阶段。`requests.json` 保存已发送的历史证据。

| **策略** | **最终正确** | **改对** | **改错** | **复核请求** |
| --- | ---: | ---: | ---: | ---: | ---: |
| 既有条件复核 | 4/7 | 2 | 2 | 8 |
| 加设主诉要求 | 4/7 | 1 | 1 | 4 |

`req-h01` 的粗条件误导改判被扣留。`req-h02` 同样缺少主诉标记，其有益纠正也被扣留。`req-h03` 在两组中均改对。`req-h06` 使用含义过宽的 `request:restore-access`，两组均改错。计数反映预设答复下的门控行为。

这套工单用于方法验收。较早的民用盲测数据和复跑入口见[民用工单盲测](../support_tickets_v1/README.md)。

## 个人网关的批量对照

`compare_personal.py` 对选定的冻结工单流程连续执行初判、两种条件复核和离线评分。两组共用初判和只读种子库。种子的类别取自已校对的合成工单参考标签，模型请求只获得条件复核允许的证据。输出的 `comparison.json` 按案例记录改对、改错和持平，并分别统计各环节的请求及用量。

先看所选案例的请求上限。`--case-id` 可以重复。

```bash
python3 -B docs/experiments/request_guard_v1/compare_personal.py --case-id req-h02
```

使用个人网关时，由当前终端提供 `LLM_BASE_URL`、`LLM_MODEL` 和 `LLM_API_KEY`，在确认预算后加上 `--live`。请求达到总上限即停止。每次初判和复核的输出上限分别为 96 和 160 Token，输入另计。以下命令从仓库根目录执行，输出目录须为新目录。

```bash
python3 -B docs/experiments/request_guard_v1/compare_personal.py \
  --case-id req-h02 --live --max-requests 3 --out-dir tmp/knowledge_applicability_live_h02
```

Windows Python 运行时，将 `--out-dir` 指到 Windows 本地磁盘，例如 `%LOCALAPPDATA%` 下的独立目录，以便 SQLite 正常加锁。无付费验收用 `--fixture` 代替 `--live`。已有同一入口生成的冻结初判时，通过 `--initial-results` 重用该文件。案例顺序、模型地址和响应配置须匹配，新的总请求上限可按剩余阶段计算。

### 费用与配对口径

两组的复核指令、案例、历史上下文和响应结构完全一致时，共用第一次模型答复。每组仍各自按原有规则决定是否复核和何时停止。`logical_reviews` 记录策略实际触发的复核轮数，`calls` 记录对网关真正发出的请求。`reused_reviews` 指向复用的请求序号。请求用量记在首次发送的组。

这项配对用于观察知识门控的差异。共用答复的轮次只产生一次模型采样。下一批可固定 `req-h02` 和 `req-h03`，分别检查缺少主诉标记的同类历史、具备主诉标记的匹配历史。两条工单合计最多 6 次真实请求，输出预算上限为 832 Token，输入另计。

```bash
python3 -B docs/experiments/request_guard_v1/compare_personal.py \
  --case-id req-h02 --case-id req-h03 --live --max-requests 6 \
  --out-dir tmp/knowledge_applicability_live_h02_h03
```

`--live` 也支持在本机交互终端补入缺少的环境值，API Key 采用隐藏输入。
