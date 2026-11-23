# 官方自测数据配置

官方自测文件由团队通过允许的渠道取得并保存在本机。公开仓库中的 `data/support_tickets/` 用于民用工单实验，官方自测数据位于独立的本地 `data/selftest/`。

## 放置数据

将完整的官方自测 JSON 文件放入仓库根目录的 `data/selftest/`。保留官方文件名，并让 JSON 位于该目录顶层，避免在解压后多套一层目录。当前完整输入输出测试预期读到 10 个场景文件。`.gitignore` 已将这一数据目录留在本地。

## WSL 输入校验和测试

从仓库根目录执行。数据放在团队约定的其他获准目录时，把 `DATA_ROOT` 设为该目录的绝对路径。

```bash
export DATA_ROOT="$(realpath ./data/selftest)"
cd dev
python3 -B -m src.main --task all --test --validate-only
python3 -B -m unittest discover -s tests -p 'test_io.py' -v
```

`DATA_ROOT` 指向包含 JSON 文件的目录。放在默认位置时，`test_io.py` 也可以自行找到 `data/selftest/`。输入校验检查文件名、字段与维度。自测套件中的固定值夹具用于核对输出目录、同名文件和 JSON 结构。其结果只说明接口是否正常。

## Docker 只读挂载

在仓库根目录运行以下命令。容器的 `DATA_ROOT` 指向镜像约定的 `/input`，本地数据以只读方式挂载。当前账户需要具有 Docker 运行权限。

```bash
b05_data="$(realpath ./data/selftest)"
docker build -t b05-dev:local ./dev
docker run --rm --network none \
  --mount "type=bind,src=$b05_data,dst=/input,readonly" \
  b05-dev:local --task all --test --validate-only
```

相关入口见 [README](../../README.md)。协作和测试记录要求见 [CONTRIBUTING](../../CONTRIBUTING.md)。
