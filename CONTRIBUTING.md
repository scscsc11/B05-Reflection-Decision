# 团队协作指南

`main` 由队长维护为稳定主分支。各成员在自己的开发分支完成工作，通过 Pull Request 提交给队长检查和合并。分支名、文件所有权与接口边界以 [V1.3 团队总任务书](docs/team/00_B05团队总任务书.md)及个人任务书为准。

## 开始和同步工作

先保存或提交当前分支上的改动，再同步 `main`。

```bash
git switch main
git pull --ff-only origin main
```

首次从同步后的 `main` 创建自己的分支。下例使用研究生 A 的分支名，其他成员使用任务书上对应的名称。

```bash
git switch -c task/gradA-reflection-integration
```

已有开发分支时，切回自己的分支，按需要将已同步的 `main` 合入该分支。接口或文件所有权需要变更时，先和文件负责人对齐。

## 提交与 Pull Request

1. 用 `git status --short` 和 `git diff` 核对改动，让每次提交对应一项可复查的工作。
2. 用 `git add -- <本次路径>` 选择文件。提交前查看 `git diff --cached`，确认只有本次任务范围内的内容。提交说明写明动作和对象，例如 `docs: add selftest setup instructions`。
3. 将当前开发分支推送到同名远端分支。首次可用 `git push -u origin HEAD`，之后用 `git push`。
4. 创建 PR，base 为 `main`，head 为自己的开发分支。由队长在检查通过后合并。开发提交留在各自分支。

PR 说明包含改动范围、接口变更、测试命令、实际结果和记录位置。只有结构或模拟验证时，写清验证对象和网关类型。凭据、官方原始资料和本地实验产物按授权范围另行管理。

## 遇到冲突

在自己的开发分支上执行 `git fetch origin`，再将 `origin/main` 合入自己的分支。通过 `git status` 找到冲突文件，逐段核对两边改动。涉及其他成员的文件或接口时，与该文件负责人和队长共同决定保留的内容。解决后暂存冲突文件，运行受影响的测试，再提交并正常推送。需要放弃本次未完成的合并时，先和队长确认当前分支状态。
