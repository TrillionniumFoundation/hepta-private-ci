# 全仓资格验证记录

这份记录对应研究分支在 `469670e8e5a88432e5ff2ddd5355bde5238e98de` 时已取得的回执。后续候选的结论按文件中记录的源树和可执行文件分别读取。PR 的当前总体状态以当次 GitHub Checks 为准。

| 检查 | 原始运行结果 |
|---|---|
| Rust 1.96.0 原三包严格检查 | 全目标 Clippy 两次成功，第二次使用 CI 原命令。普通全目标检查和三包格式检查成功。6 个外部测试目标共 8 项通过，另外 14 项运行时、3 项面板和 8 项在 UID 0 下执行的资格测试通过。 |
| 调用约束 | 原验证程序扫描 9,146 个 Rust 文件，1,652 条调用边界及 826 条源码保护全部通过。160 个相关模块的 1,352 个既有用例通过。增加两个 Rust 测试文件后，另一次原全仓检查扫描 9,148 个文件，三包严格检查再次通过。[冻结候选的逐项验证摘要](frozen-source-guard-and-strict.json) |
| ARM 原生复核 | 独立 Apple Silicon 机器检出 469670e8。原启动包装器 68/68，原平台路径 10/10，零跳过。 |
| Windows 队列 | 上个提交在托管 Windows 分片中两个就绪文件均超时。候选沿仓库已有 Python 解释器走原钩子路径。在 GNU 上按 Bazel 原 8 MiB 测试栈，基线 3/3、候选 4/4。GNU 默认栈下，两版的 caller abort 用例都触发栈溢出。469670e8 的 Windows 分片随后还记录两项持久化拒绝用例超时。最终候选沿仓库原有的 Python fixture 检验四项队列生命周期，同时用独立的 Windows 测试保留实际 PowerShell 钩子的行为覆盖。在仓库原 8 MiB 测试栈配置下，四项生命周期用例和两个钩子用例在 GNU 宿主实际 6/6 通过。[原测试断言、时限和源文件绑定](queue-and-operator-bindings.json) |
| 独立受保护进程 | 四个原本须显式选择的测试都实际启动了独立子进程。在基线 musl 和 469670e8 GNU 两个构建上，学习注册和 Q24 冷恢复均成功。发布随后连接已退役会话、受控确认丢失后的初始恢复均失败。不同目标的两份回执分别保存。 |
| 500 毫秒原时限 | 相同读取流程的 16 KiB 缓冲实验中，基线 0/6，候选 0/6。另一次独立实验在两个丢弃计算结果的调用点执行同一组结构验证，真实使用摘要的调用照常计算摘要。该实验的基线 0/6，候选 5/6。保留失败的全过程和原时限。 |

`validation-source-receipts.zip` 含三包严格编译、原调用约束、队列、ARM 与 musl 分阶段计时的机器可读原始证据。每个子包列出了自己的源码或 ELF 标识。`PROTECTED_RUNTIME.json` 和 `protected_runtime_receipts.zip` 保存两目标四用例的原日志和退出码。12 次缓冲对照保存在相邻的 [next_use](../next_use/)。


在同一原始 musl 测试的两轮分阶段计数中，每个完整证据请求都完成 600 次 CurrentStore 加载及绑定摘要、300 次成功的选择验签及 300 次最终用途验签。CurrentStore 此处走原测试的 Store::Test 分支，不能将次数解释为生产主机后端的读盘数。基线与结构候选处理未截断常规请求的中位时长分别为 550.094 和 502.826 毫秒。[四个 crate 的完整原始计数](multi-crate-native-evidence.zip)

## Bellman 算子覆盖率和性能

在 469670e8，原 CI 的 37 个用例全部通过，行覆盖率为 2,122/2,902（73.12%），原 85% 检查退出 1。候选补测覆盖了真实签名账本上的记忆训练、终止状态的冻结与修订，以及传感器几何和工作量上限。同一命令运行 45 个测试，全部通过，执行了 2,632/2,902 行（90.70%）。三个模块分别覆盖 161/164、179/200、276/293 行。七项原发布构建性能测量均达标，百万样本拟合的 p99 为 5,227 毫秒，限值 300,000 毫秒。

[完整覆盖率 JSON、性能结果和映射回执](learning-operator-frozen-source-evidence.zip) 绑定到包内指明的本地源树与有序双亲合并。随后调整汇合作业的工件下载目录，逐文件重算 41 个资格输入的摘要，并在两个提交模式重新生成和验证全部 20 个算子映射。[目录修复后的原始映射](qualification-download-path-maps.zip)用工作流固定版本的归档程序复核，旧下载目录的原校验程序找到 0/4 个实际测试产物，修正后找到 4/4 个，长度和摘要相符。[下载和校验的逐项原始结果](verified-rehydration.json)

GitHub 对带有证据附件的最终提交独立产生回执。

[已发布修复](https://github.com/TrillionniumFoundation/hepta-private-ci/commit/469670e8e5a88432e5ff2ddd5355bde5238e98de) · [对应的完整托管运行](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/45917805750) · [上一提交已通过的原 musl 作业](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/45914954824/job/140232518511)
