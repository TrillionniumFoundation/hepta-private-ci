# Objective owner：当前 67 源的已完成原生任务核验

## 结论

GitHub 原任务 `42123581408 / 127581904963` 的 owner 包限定资格通过。实际运行源为 `67cc5c28c4adf82f6ef97c34a18b8b13f3ac27ed`，完整树为 `3982ba56dc5a3f1da0c1de7ea57992f88125c359`；这是原工作流检出的 PR head。memory、Agentd、启用 desktop Objective UI 的 Agentd 三个库命令均通过，原 scoped fix 和前后 fmt 也通过。

| 原命令组 | 实际执行并通过 | 失败 / error | nextest skipped | JUnit 中 skipped 节点 |
|---|---:|---:|---:|---:|
| memory | 327 | 0 / 0 | 8 | 0 |
| Agentd | 242 | 0 / 0 | 1 | 0 |
| Agentd + desktop-objective-ui | 247 | 0 / 0 | 1 | 0 |

三份原 stderr 的逐例 `PASS` 集合与各自 JUnit 全部 testcase 逐项相等。nextest 原始摘要明确存在 8/1/1 个跳过项，而 JUnit 没有列出它们；不能以 XML 无 skipped 节点报告零跳过。原件没有这些 skipped 用例的名称，本包不推测其身份。816 是三个命令的执行次数之和，包含两次 Agentd 运行中重复的 242 例，不能称为 816 个不同测试。

该结果不授予全工作区、Bazel、native guest、生产 checkpoint 或私有 full-jobs=4 资源门资格。原任务实际 `CARGO_BUILD_JOBS=1`、nextest `--test-threads 1`、`--retries 0`、`dev-small`；本包没有触发任何新运行、重跑或取消。

原始链接：[GitHub job](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/42123581408/job/127581904963)，[固定工作流源码](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/67cc5c28c4adf82f6ef97c34a18b8b13f3ac27ed/.github/workflows/hepta-objective-owner.yml)。

## 完整性与来源绑定

run 的 artifact 列表仅一页，`total_count=1`，唯一 artifact 为 `13471885720`。完整 ZIP 为 1,071,142 字节，SHA256 `4d41426b73b32fa6235034e1183dbb7168ed096e2e4a03f22ce81d26ad22eab2`，与 GitHub 官方 digest 和 size 全等。52 个成员均完整解码并通过 CRC；没有重复路径、越界路径或 symlink。包内原 inventory 的 51 项逐项 bytes/SHA256 与 ZIP 相等，额外一项是 inventory 自身。完整原 ZIP 被保留，未用抽取的摘要替换任何成员。

完整 decoded job console 为 1,606,119 字节，SHA256 `74fbbd060d64f9a1ae18bd91f3a483ca0a8f62fc5e7bab58828d89a5bf33c370`，Git blob 计算身份 `5ca1c1c9543c21ff9647dcb90dfd32ada53e9f22`，CR 数量为零。本包对其全部字节完成核对；持久原件复用同一 0244 增量证据包的 `original/job-127581904963.original.log`，避免重复存放。该计算身份不被伪称为一个单独实际创建并 GET 的 Git blob。离线复验必须显式提供这个完整共享 console 文件，并且全字节身份必须匹配。

原 artifact 的 `source.json` 记录 10,582 个实际 checkout 叶子。离线工具重算全部 1,571 个 Git tree 节点得到 `3982ba56...`，同时绑定已经完整保存的真实 commit GET 和 root-tree GET。`files_sha256=a10cbc307f149ff3548efb53bf89b75780c039fad91718c543ec940e0ff5d30c` 已按原 JSON 编码重算。17 个锁文件、12 个命令的 24 次前后 source guard、最终 guard 全部一致，原 `source-drift.patch` 为空。

固定工作流实际 blob `22b551a58fa9900560767a2b39da5d3f1d01aeea` 的完整 heredoc runner，与 artifact 中 16,507 字节 `run_owner.py` 全文相等；没有执行 artifact 内的 Python 代码来替代审查。四个相关源码均保留实际完整 Git GET 和所有字节，并与 source.json 的 Git、SHA256、bytes 三者绑定。原 12 个 command receipt、完整 stdout/stderr 和 result.json 的副本逐项相等，退出码均为 0。

## 通过结果的具体范围

memory 的 10 个 required Objective sender 用例全部在原 JUnit 和逐例 PASS 行中。Agentd 的 bridge 3 例、bootstrap 3 例、真实 control admission/cancellation 7 例全部通过；完整组计数为 production composition 9、Notes 6、Objective sender bridge 3、production authority 5、final-use issuer 7。desktop feature 运行相对普通 Agentd 的集合恰好增加 5 个 UI 用例，原 242 例均保留。

这 5 例覆盖原 workspace 的重复点击与取消、lost-ack 后恢复不再发送、window generation/draft 绑定拒绝跨窗采用、owner session rotation 关闭等待中的 checkpoint、提交前取消保留 draft 且不派发。它们通过原 fixture 进入既有组件，测试源码仍明确 fixture issuers 是 qualification-only；不能据此宣称外部生产签发器或生产 checkpoint 已实现。

实际 generic-append 负控有可核源码和已执行结果：两个 recovered ticket 使用同一个真实 owner fixture，在 barrier 前都观察空 history；分别调用原 `retain_observation` 后，两份相互矛盾的测试 history 都留在 snapshot，长度为 2，checkpoint fixture 共记录 3 次测试 ACK（包括最初 retention）。对应 checked 正例使用 `retain_observation_checked` 在事务内重新检查，恰一份成功、另一份 `IdentityMismatch`，两次检查观察长度 `[0,1]`；重复 winner 的 ACK 不增加 retained observations 或 recovery anchor，并执行原完整 semantic startup audit。

这是一对同一 owner fixture 内的真实 API 负控和正例，不是 Root54、Current→FinalUse、独立 pool / 独立进程、进程崩溃恢复或生产 genesis 的验收材料。源码也明确 contradictory publications 是未认证的测试 metadata；本包不把测试 ACK 改写成生产授权。

## 复验方法与工作记录

运行 `python3 verify_evidence.py --console /完整共享原件/job-127581904963.original.log --output replay.json`。工具只解析 GitHub API、原 ZIP、JSON/XML、源码字节和完整 console，不编译或运行产品。当前复验退出码为 0，stdout 与 `VERIFICATION.json` 的 116,203 字节完全相同，stderr 为空。

初次离线工具有两个实现错误，原失败也保留：第一次把 attempt.json 原环境变量名错写为小写，第二次 heredoc header 的 DOTALL 通配符误选到后面的 finalization 块。修正只发生在本包的离线 verifier；原 workflow、原 artifact、原源码和原生结果没有修改。两份旧 verifier、stderr 和原因记录分别保存在 `verification-harness-first-iteration/` 与 `verification-harness-second-iteration/`。
