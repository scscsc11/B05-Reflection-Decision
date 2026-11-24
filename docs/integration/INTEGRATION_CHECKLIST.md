# 集成验收清单

## 本地回归

在仓库根目录进入 `dev` 后运行以下命令。测试使用合成场景、进程内模型替身和临时数据库。

```bash
cd dev
python3 -B -m unittest -v tests.test_runner tests.test_knowledge \
  tests.test_reflection_live tests.test_team_integration
```

按[接口契约](../architecture/INTERFACE_CONTRACT.md)检查以下结果。

- 主程序按场景顺序调用注入的处理器，交付两个模式目录。错误样本、非法返回值和写出故障均以非零退出码报告，发布回滚后可重试。检查 `tests.test_runner`。
- 工单初判与复核保留轮次、停止原因和调用记录。知识测试检查适用条件、冲突扣留、修订来源和旧库兼容。检查 `tests.test_reflection_live` 与 `tests.test_knowledge`。
- 留出案例共用冻结初判。评分前校验结果文件，评分进程打开并核对独立答案。测试同时检查中断续跑、经验版本和原始产物完整性。检查 `tests.test_team_integration`。

命令行入口抽检覆盖输入读写与退出码。

```bash
python3 -B -m unittest -v \
  tests.test_io.IoTests.test_json_syntax_encoding_and_duplicates \
  tests.test_io.IoTests.test_matrix_and_vector_shapes \
  tests.test_io.IoTests.test_result_schema_does_not_assume_index_base \
  tests.test_io.IoTests.test_formal_entry_reports_unimplemented_without_writing \
  tests.test_io.IoTests.test_validate_only_checks_inputs_without_writing_fixtures \
  tests.test_io.IoTests.test_fixture_uses_output_dir_environment \
  tests.test_io.IoTests.test_fixture_leaves_existing_output_untouched
```

本地交付验收通过 34 项测试，覆盖以上用例。结构检查采用合成文件，反思与评分验收采用进程内替身。民用工单的冻结数据和分阶段复跑入口见[民用盲测资产](../experiments/support_tickets_v1/README.md)。

## 正式联调准入

| **交接项** | **验收条件和证据** |
| --- | --- |
| 模型客户端 | 研究生 B 交付实现与配置说明。获授权后，以民用工单验证真实响应的结构、时间预算及错误返回，保存脱敏的模型标识和运行记录。 |
| 处理器接口 | 研究生 B 交付实现，本科生一交付独立接口测试。确认 `process(scene, mode)` 可装载，两种模式的返回值及错误传播满足契约。在正式输入上核对结果的合法范围。 |
| 候选容器 | 本科生三提供候选镜像与运行记录。核对固定入口、只读输入挂载及输出文件齐备性，保存镜像标识、运行命令和退出码。 |
| 场景材料 | 队内提交确认的材料包。核对文件版本、清单和报告的一致性，验收记录标注所用材料来源。 |

研究生 A 复核候选版本的提交号、输入版本及测试证据。运行日志和结果写入独立目录。每份记录标注证据来源，分别使用固定值夹具、进程内替身、脚本化网关、真实模型运行或官方评测等实际来源。
