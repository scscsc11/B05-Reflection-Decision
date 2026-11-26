# Docker 运行说明

本说明以当前 `dev/Dockerfile`、`dev/run.sh` 和 `dev/src/main.py` 为准。正式处理器尚需 `dev/src/processor.py`；固定夹具仅验证接口，不代表算法成绩。

## 构建与目录

从仓库根目录运行 `docker build -t b05-dev:local ./dev`。镜像使用 `python:3.11-slim`，容器工作目录和入口分别为 `/app/program/solution`、`/app/program/solution/run.sh`。构建时需要获取基础镜像及 Python 依赖；运行下面的接口检查时关闭容器网络。

官方自测 JSON 放在本地 `data/selftest/` 顶层，不提交仓库。容器内只读挂载到 `/input`，`DATA_ROOT` 默认为 `/input`；独立的空输出目录以可写方式挂载到 `/output`。不要把输入和输出指向同一目录。

## 快速检查

在带有 Docker 的 Bash/WSL 环境，从仓库根目录运行：

```bash
bash dev/tests/team_docker_smoke.sh
```

也可传入获准的官方数据目录：`bash dev/tests/team_docker_smoke.sh /绝对路径/自测数据`。脚本为每次运行创建独立临时目录，先构建候选镜像，再运行 `--task all --test --validate-only` 和 `--task all --test --fixture --out-dir /output`。输入挂载只读，输出不覆盖其他成员的结果。结束时打印记录目录；其中有 `image_id.txt`、`commands.txt`、`exit_codes.txt`、`build.log`、两轮运行日志、`output_check.log` 和 `output_files.txt`。输出检查复用仓库已有的 `check_outputs`，核对文件名、数量和 JSON 结构。

`--validate-only` 只读取、解析和校验输入，不写结果。`--fixture` 在 `/output/norethink/` 和 `/output/rethink/` 生成与输入同名的固定值 JSON；这些数字没有算法意义。`--out-dir` 指定结果目录；`--test` 目前仅作为入口标志记录，`--task all` 走场景批处理。默认正式模式需要处理器，未实现时会返回 3。`--task support-tickets` 是另一个依赖模型网关的民用工单基准，不属于这次官方自测冒烟。

## 退出码和日志

`dev/src/main.py` 成功返回 0，输入、输出或处理器运行错误返回 1，缺少正式处理器返回 3。冒烟脚本自身在输入目录缺失时返回 2，找不到 Docker 时返回 127；构建和容器运行失败时转发相应退出码。先查看记录目录的 `exit_codes.txt`，再看对应的 `build.log`、`validate-only.log` 或 `fixture.log`。运行日志由容器标准输出和错误输出保存，脚本不打印任何模型密钥。

集成后按队长给出的候选提交号检出版本、运行脚本，并检查输出结构。正式提交时把代码包、方案包、成果简介和输入输出目录一起传给 `dev/tests/check_submission.py` 做离线结构核对；仅夹具通过时，只报告容器、输入和输出接口已验证。
