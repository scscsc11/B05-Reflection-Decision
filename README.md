# B05 反思式决策

本项目维护通用反思、版本化经验库、离线对照实验和赛题软件接口。现有民用工单基准用于验证初判、复核、经验筛选和评分流程。

## 当前进度

- 官方格式的 JSON 输入校验、双目录写入及 Docker 入口已有夹具验证记录。
- 民用工单已在脚本化 HTTP 网关下跑通反思和盲测。盲测将留出答案保存在推理输入之外，供结束后的离线评分使用。
- 真实模型联调、正式赛题专用实现和官方评测仍待完成。`dev/src/processor.py` 与 `dev/src/processor_runtime.py` 是任务书中的待开发文件。

## 目录结构

| 路径 | 内容 |
| --- | --- |
| [dev/src/](dev/src/) | `main.py` 入口、`scene_io.py` JSON 读写、`llm_client.py` 模型通信、`reflection.py` 反思、`experience_store.py` 知识库、`score_benchmark.py` 离线评分 |
| [dev/tests/](dev/tests/) | 接口、调度与知识库测试，模拟网关，盲测运行器和提交结构检查 |
| [dev/Dockerfile](dev/Dockerfile) · [dev/run.sh](dev/run.sh) | 镜像构建及容器入口 |
| [data/support_tickets/](data/support_tickets/) | 民用工单样例和参考标签 |
| [docs/team/](docs/team/) · [docs/operations/](docs/operations/) | V1.3 团队任务书和本地操作说明 |

## 环境与启动

使用 Python 3.11 或 3.12。已有 Windows 10 + WSL2 Ubuntu 24.04 与 Docker Engine 的运行记录。[Dockerfile](dev/Dockerfile) 使用 `python:3.11-slim`。当前 Python 依赖文件只包含注释。

从克隆后的仓库根目录进入 `dev/` 构建镜像。

```bash
cd dev
docker build -t b05-dev:local .
```

获准取得自测数据后，从 `dev/` 做一次本地输入校验。

```bash
DATA_ROOT="$(realpath ../data/selftest)" python3 -B -m src.main --task all --test --validate-only
```

`--validate-only` 只解析和校验输入。`--fixture` 生成固定值结果以验证接口。容器的输入挂载、输出目录和测试命令见[官方自测数据配置](docs/operations/SELFTEST_DATA_SETUP.md)。

## 运行现有测试

以下两组测试使用本地夹具或临时 SQLite 库，从 `dev/` 执行。

```bash
python3 -B -m unittest discover -s tests -p 'test_knowledge.py' -v
python3 -B -m unittest discover -s tests -p 'test_runner.py' -v
```

完整的 `test_io.py` 还依赖 10 个官方自测 JSON。公开仓库提供民用工单，通过[自测说明](docs/operations/SELFTEST_DATA_SETUP.md)配置获准的官方数据后可运行全套测试。

## 五人团队分工

以 [V1.3 团队总任务书](docs/team/00_B05团队总任务书.md)和各个人任务书中的文件所有权与协作边界为准。

| 成员 | 职责 | 开发分支 |
| --- | --- | --- |
| [研究生 A（队长）](docs/team/01_研究生A_队长个人任务书.md) | 反思、知识、实验评价和系统集成 | `task/gradA-reflection-integration` |
| [研究生 B](docs/team/02_研究生B_大模型与处理器个人任务书.md) | 真实大模型接入与处理器核心模块 | `task/gradB-llm-processor` |
| [本科生一](docs/team/03_本科生一_处理器测试个人任务书.md) | 处理器运行支撑、接口测试和回归 | `task/ug1-processor-support` |
| [本科生二](docs/team/04_本科生二_场景与实验个人任务书.md) | 场景材料、一致性核对和实验证据整理 | `task/ug2-scenario-evidence` |
| [本科生三](docs/team/05_本科生三_Docker与提交个人任务书.md) | Docker 运行说明、提交结构和候选版本容器检查 | `task/ug3-docker-submission` |

`main` 由队长维护为稳定集成分支。成员在各自的开发分支提交，使用 Pull Request 请队长复核和合并。具体命令、提交记录与冲突处理见 [CONTRIBUTING.md](CONTRIBUTING.md)。

## 真实模型 API 配置

在授权网关的运行环境中注入以下变量，启动测试的进程需要能读取它们。

| 环境变量 | 用途 |
| --- | --- |
| `LLM_BASE_URL` | 官方授权的网关基础地址。客户端自动追加 `/chat/completions` |
| `LLM_API_KEY` | 该环境提供的调用令牌 |
| `LLM_MODEL` | 该环境指定的模型名 |

授权网关确认支持 JSON Schema 时，可设 `LLM_USE_JSON_SCHEMA=1`。`LLM_TIMEOUT_SECONDS` 可设置单次请求超时。凭据由授权环境注入，日志和提交中只保留非敏感验证信息。

授权环境能够从 Docker 访问网关时，可从 `dev/` 使用已构建镜像运行民用工单对照。

```bash
b05_run_dir="$(mktemp -d)"
python3 -B -m tests.run_blind_trial --image b05-dev:local \
  --seed-id ticket-01 --include-guarded --out-dir "$b05_run_dir"
```

脚本以种子案例建立知识库，再运行留出案例，最终写出 `offline_score.json`。实时运行需要模型额度。若使用本地测试网关，须显式加 `--simulated-gateway` 并在报告中标记该结果。
