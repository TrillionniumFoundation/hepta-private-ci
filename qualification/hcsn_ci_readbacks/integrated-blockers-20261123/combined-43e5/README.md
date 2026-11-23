# 九项 Rust 修复在同一源码上的核验

候选 43e5da1bb81369e4e999adfa8558f5ccb5460eb6 基于 #7016 的 e3277e9677688be5c4c235a7a127f0b51e373399。合并了五个内部枚举、两个内部未使用项和两个私有流构造调用。实际原命令在同一台原生 Linux 机器为两个源码分别编译三个 crate。基线报 124 项，候选报 115 项，退出码均为 101。逐文件、逐消息及重数校对，减少的正好是预期九项，新增零项。候选仍有参数数目 69 项、枚举大小 35 项、未使用代码 11 项，分布在 90 个文件。strict-remaining.json 列出原报错位置及匹配的真实源代码行。各变更提交的证据可另行检查。[两个私有流](../private-stream-binders/) · [两个内部未使用项](https://github.com/TrillionniumFoundation/hepta-private-ci/tree/02065f56ba5709313b09eb9525bde59161040697/docs/learning/evidence/agentd-material-projections-20261123) · [五个内部枚举](https://github.com/TrillionniumFoundation/hepta-private-ci/tree/2a56619d93df25de8df24863e8f8c6814a107678/qualification/hcsn_ci_readbacks/agentd-private-enums-20261123)

| 原始测试 | 基线 e327 | 候选 43e5 |
| --- | ---: | ---: |
| 原普通用户用例 | 62/62 | 62/62 |
| 原真实 UID0 用例 | 29/30 | 30/30 |
| 合计 | 91/92 | 92/92 |

两个真实 ELF 哈希不同，夹具源码及其 Git 标识逐项相同。基线唯一失败为 resident_root_queued_admit_cancellation_sends_no_frame_and_consumes_channel。该基线在最后的读回错误类型断言失败，另外的旧源码配对也出现过同名失败。候选本次通过；保留配对作业的红色终局，单次成功无法确定是哪项变化导致结果不同。比较使用原限制、原断言和普通、特权两类进程的真实身份。[原配对作业](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/45133193126)

20 个相关源码测试套件在含全部 9,141 个 Rust 文件的实物目录中运行，138/138 通过。对 Git 两个根树逐层比较，Rust 差异只出现在 agentd/src。相对已独立核验的 c6a 快照，共 16 个 Rust 文件变化。每个候选文件都实际散列，换回 16 个旧哈希后完整路径哈希集与已知 c6a 集完全相等。同时从候选 Git 树核对全部六个调用清单与执行器输入。完整文件集核验范围及确切身份见 physical-identities.json 和 official-inputs.json。

下载本目录可直接用 Python 标准库从两个原始作业 ZIP 重算逐项结论。original exit code、每个实际进程的 UID、两份完整编译输出及测试日志都在原 ZIP 中。

```sh
python verify_full_pair.py strict.zip native.zip cases.json expected_removed.json --strict-sha 762e51e6c0485e228bbf52f0e4c0dfdc438724cf6d38702d66e7d367a0053f3c --native-sha fc7fbc887f77883d185dd773c866560f02d3b118f46be196d59fe956dce3c115 | cmp - result.json
```
