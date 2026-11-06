# 并行项目增量：2026-11-06 07:06 UTC 观察

本增量补充既有全量元数据普查，不改原 23 项 blocker 的退出条件或状态。审计结论仍为 16 项限定闭合、6 项开放、1 项科学保留。

## 范围与来源

07:06:59 UTC 发出的三个独立读取分别取得 updated 搜索和按更新时间倒序的两页 REST PR 列表。两页各 25 条，共 50 个不同 PR；其中 38 条 updated_at 不早于 03:35:10 UTC。搜索只返回 36 条，遗漏本轮 REST 已见的 #4797、#4884。三次读取不是原子快照；这 38 条是本次有界观察，不是新的全库总数或逐行代码审计。

另外取得 #4855、#4907、#4895 的实际 commit 对象，#4855 的 35-commit 比较，以及 #4932、#4934 各自的一提交比较。完整原返回均保留。对 #4929 和 #4930 各读一份固定 README 与 provenance，共四份源码文档；它们描述实现和接受边界，不能替代原生运行。

## 实际 ref 与正文必须分开

| 项目 | 实际 head / tree | 本次核实的事实 | 接受边界 |
|---|---|---|---|
| W0–W7 #4855 | `ef0cf55a747ee1fa966ede6804b3652792c9961f` / `bfccbc514aafb9cafe194430cfc111158b402ac5` | 从正文仍称“唯一已发布88”的 `1a2add869929ef0c1a32f42689359176480b3a1d` 前进 35 commits，57 changed paths，behind=0。实际 commit message 是 exec 推送事件夹具修复。 | 正文中的 source88、Mac93–104、准备113等旧范围保留各自身份，不转授 ef0；本轮没有逐行接受全部57路径。 |
| Neuron owner #4907 | `62e60b9c83f1c0b1b4c03b332cc9ff161b1ac65e` / `9f71d5cddc3d5cdeac0db3411cdac65fbb758751` | 实际 parent 是正文中的 `2f0ee748017522f39ef40c26b5c8801fa3441fda`；后继 commit message 为执行既有 Windows rustfmt 输出。 | 正文对2f的 fix/strict/helpers 成功和 scoped 编译 ENOSPC/取消，不是62源测试通过；本轮未审核这次后继的全部格式差异。 |
| PQ/Chain #4895 | `dd32a0d510cbeb3dfed0554d982c75168a59d95d` / `d0970a07c04d174aca4de13574a3f6ddafa67995` | 实际 parent `71467e27c548e90aa5546ae7ca8b3015fb38a6f3`；commit 记录新增 Windows root-pin 控制的独立留存，并明确尚无该源原生观察。 | 既有 Hepta09de43ba×Chain254033da 源审和尺寸修复证据不转授新head；paired原生、可信binary来源、普通consumer仍分别验收。 |

这两处正文滞后说明进度报告必须读取实际 ref/commit/tree，不能把 PR 正文中的“当前”作为唯一来源。本增量不改写其他工作流维护的 PR 正文，也不把另一个分支的成功计入本产品候选。

## 新增工作如何进入后续路线

### Joint 生成桥接 #4929

固定 head `7391c3dc3b0a496b62be4c6cf2769d2ae0c9db75`。已读文档将职责明确分给 pure proposal worker、durable inference control、Cell journal 与独立 delivery ACK：未决操作使用相同绑定读取原结果，reopen 不获得第二次 dispatch token。协议限制 weights 8 MiB、public 1 MiB、state/delta 各 65,536 B、prefix 262,144 B 和 stderr 16 KiB。

这些是固定源码文档和 provenance 明示的合同。该阶段仍标记 DENY_ALL；synthetic 67张量用于真实计算与生命周期路径，不能验证历史 trained weights。CPU、能耗、完整保存/恢复/fsync 未测项目保持未知。普通 service 的 same-owner reopen 也不等于跨 manifest 模型采用。下一门是固定候选 strict/helper/scoped/full 原生执行，随后再做实际模型和公平固定专家对照。

### V13 学习内容闭包 #4930

固定 head `dd1adf3defc5f1b1bcf3358419e23490e24b9a6a`。已读 README/provenance 明确复用固定 V13 Adapter.load，先约束 ZIP/NPY 库存与资源，再核完整参数、Adam、PCG64、sampler、cursor以及真实source/encoder/data内容。输出五成员身份，不授予质量、发布或采用许可。V13是MiniLM embedding上的残差分类器，并非Joint生成模型。

作者报告该源11个Python测试通过；本增量没有取得并独立重放其完整原生/测试归档，因此该数字只归属于作者报告。即使这些内容检查全过，真实参考资产、SourceOwner live frontier、质量门和Rust产品组合仍须独立接受。

### Caller inventory 与 OpenSSH 夹具

#4932 `7d643ffe5859ad65f440ae31bb6c559b8913d084` 的实际比较只改 CALLERS.toml，12 changed lines，涉及四个现有边界。新增 `automation_effect_host_pq.rs` caller，同时两处 marker 从更具体的表达式缩短为共有表达式；必须以原typed-caller验证器和完整caller源审证明正确，不能仅按“清单更新”授予授权资格。本增量未将该路径引入67基线候选。

#4934 `92afaa8100b6a82fa6b6905b255de1cbdf56df34` 的实际比较只在 `sshsig_differential_tests.rs` 将 Stdio 导入改为 `{Command, Stdio}`。其 parent/base 是上述 ef0 源；原 Clippy/native和merge接受仍待该分支自己的结果，不将这个修复套到没有同一源问题的67基线。

### NDU 科学采用

#4921 `cb5019ae86bc52c9baff27858a3ee21cafc89ac5` 的作者报告继续明确 NO_GO：有限实验对同数据 myopic VOI 为0胜/143平/1负，144格原主生命周期门均未过，真实冻结LLM确认未运行。150个工程测试和84个数学断言不能改写这项失败。这里保留该报告的来源和限定；并未取得其完整科学归档作新独立验证，也没有将它等同于原B18的独立2×2、D−B采用门。

## 整合决定

当前先将已逐路径复核的67基线工程修复与真实依赖生成产物收敛为单一产品候选；上述并行分支保留为后续donor队列，不整体搬入。下一阶段按实际owner合同依次核Root/Current、普通UI caller、durable dispatch、真实provider/target与取消/丢ACK/重启；Cell的内容绑定、数值质量、采用、更新和撤回分别验收。外部consumer和科学采用继续保留各自独立退出条件。

本增量没有请求私有容量、运行新native、调度/重跑/取消CI，或更改任何其他分支ref。
