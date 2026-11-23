# c12 的原工作流

#7016 c12ee03f 的首轮 blocking-ci 已终结。46 个作业中，32 项成功、6 项按原工作流条件跳过、7 项失败、1 项取消。失败包括 Windows 汇总、严格构建汇总与总门。原源码与确定性合并树各有 115 项相同诊断。完整 musl 的 Q24 测试在连接关闭后返回 OwnerUnavailable。Windows shard 4 的四个隔离正例和分离会话超时均保留在原报告。[作业名册](../c12-blocking.json) · [两树严格输出](original-strict-diagnostics.zip) · [Windows](../windows-capability/NATIVE.md)

repo-checks 原作业从 08:32:16 至 09:12:31，配给 40 分钟。前置步骤占去 5 分 13 秒，权限盘点运行至作业取消，之后的仓库维护步骤被跳过。相同 c12 的独立原权限工作流在干净的同一棵树上完成 self-test 和 verify。原权限回执 770,005 字节，SHA-256 为 2de991230d84e60c8d440278ceb189e0f4111ce8b7c200a934ffc7a31257d6c3，与 c6a、e327 和 43e5 的已核原件完全一致。[c12 原权限包](caller-proof.zip) · [取消作业](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/45138928408/job/137573327174)

原 MemoryCell 构建、恢复和执行也已终结。新的 597,827,464 字节 Agentd ELF 的 SHA-256 为 1a635fa32c9dbc47bdc015db44cdcc7f011b5ff6f6a0fa3918d043757b8cc933。全量运行 208.315 秒，1,552/1,552 按全名通过，171 原忽略。四组控制全通过。两个原生子程序的哈希与 e327 相同；两个源码上的 1,723 行名册、过滤条件与忽略状态逐项一致。构建包的五个签名与实际测试包相同。[构建回执](startup-build.json) · [原测试 ZIP](startup-tests.zip) · [逐条对齐](startup-comparison.json) · [实际原工作流](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/45138928118)

在此目录持有 Python 3 时运行：

```sh
python ../memory-startup/verify_full.py startup-tests.zip --source c12ee03f3185d5a13949faca54f066dfd634e509 --digest 2946327047596b49f097857dcd548fc26a35e7c18c597e80216dffdf39a334aa | cmp - startup-tests.json
python ../memory-startup/compare_full_rosters.py ../memory-startup/e327-tests.zip startup-tests.zip | cmp - startup-comparison.json
```

c12 的 daemon 原生工作流也已终结。独立解析两份 JUnit，普通 2,849/2,849、真实 Root 68/68，零跳过；202 项学习所有者原用例覆盖齐全。随后固定基址 fmt 对历史 2909 快照找不到所属 Rust 工作区，退出 2。该工作流最终失败。仓库级取消作业已单独按原 40 分钟作业配额、同一提交与同一检查命令重试一次。[两份原 XML 与事件记录](daemon-original-members.zip) · [独立结果](daemon-result.json) · [daemon 终态](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/45138928116) · [仓库原作业第二次执行](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/45138928408/job/137602127556)

## 同源重跑的终局

仅重跑首轮取消的 repo-checks 作业，原 c12 的 40 分钟配置和命令保持不变。第二轮用时 36 分 45 秒，原权限全集检查从 09:34:47 至 10:08:07，随后仓库维护、格式、Prettier 和干净工作树均通过。整个 blocking-ci 因其他失败仍为红，最后为 33 成功、6 条件跳过、7 失败。首轮原始取消与二轮恢复分别存档。[重跑全部步骤](repo-checks-retry.json) · [二轮最终 46 项](attempt2-final.json)

单独建了产品集成源码 11e16607，包含固定基址格式、子通知和私有 bootstrap wire，净 21 项修改。对 c12 加 21 个修改、格式后继加 3 个、子通知后继加 19 个，均构造出相同完整 Git 树 b87f5d7b。各路径原 mode、修改前后 blob 可分别核验。这个等式是源码证明，原生资格仍以相同提交的真实运行作准。[精确完整树和文件清单](combined-tree.json)
