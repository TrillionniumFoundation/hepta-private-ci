# e72 原始读取递归预算：历史静态审计

状态：**仅固定 e72 源码静态审计；未运行，不能迁移到 374aa919。** e72 合成树 `e72ab40aadbfd3f69b3b272f1597ccaeb39fe75b`，来源 manifest `d0cb3d6ae0581792189d257fe63bb46af8214908`。封存前 Root 已报告新的 374aa919 增加 B 同调用证明与 C CURRENT 事务，故以下只保留历史，不是新源码失败预测。

## 已核最小结论

Root 的 `continue_original` 在每个成功 stage 后必须实际调用 `original_attestations` 并 checkpoint。4/5/6-cut 新分支只调用一个具体原始读取批次，没有再叠旧 legacy fallback。250 ms watchdog 读的是本地 Root 权限状态，不算 Trainer RPC。

从 B 执行起，B / 4-cut checkpoint / S / 5-cut checkpoint / C / 6-cut checkpoint 分别需要 **1、1、2、2、3、2** 次实际 Evaluation facade，总计 **11** 次。每个 facade 仍调用 **6** 次 common E/D/T prefix 与 **2** 次 Candidate 客户端读取。

Candidate 第一次传输为 P 页（1～17），后续同一原客户端只用一帧 CURRENT；每个已完成 T 读取及每个 Candidate 页面／CURRENT，在同一原 SourceBoundStage 上各用两次 E/D 原证据读取，远端 Material 亦两次。因此在这些客户端确实汇合于同一 Stage 的情况下，这一外层子图需要：

`16 × (11 + 2R) + 2(P − 1) = 176 + 32R + 2(P − 1)`

R 是 mandatory C checkpoint 之外额外的完整六切 Root readback；实际把最终结果交回还经过独立 readback，通常 R 至少为 1。R=0 时范围 **176～208**，R=1 时 **208～240**。这是成功路径的请求需求，尚未加 Version、S/C 原 owner、B 内部及 setup，不表示已成功执行这么多帧。

## 不混合连接身份

| 原端点 | e72 计数／边界 |
| --- | --- |
| Root common T 与 Candidate | 两条顶层连接可回到同一 bootstrap Ready owner / SourceBoundStage，底层 E/D/Material 因此合流；不能各算独立底层预算。 |
| B consuming shared-Trainer factory | m 个成员及 B receipt source 真正持同一 Arc Trainer。N 次 B 请求含 X 次新 Execute，需 `(8m+1)N+X` 个 Trainer 请求。 |
| B 独立 primary / retention | primary 为 `9N+X`；每个 retention 为 `8N`，分别计数。11 次、m=2、X=1 的 shared 情况为188，独立情况为100/88。 |
| 默认 PublicationFixture | 使用独立 fixture Trainer 签名连接；外部 SourceBound T 另外持有。不得把 resident 的176或 shared-B188 套到已运行的 first-S 失败。 |
| Version / S / C | canonical Version factories 克隆同一 shared_evaluated T/B Arc；角色不同不产生新计数器。 |
| Source bootstrap fixture | 每条 E/D/source fixture 连接确为128帧。 |
| 生产 legacy Material evidence/source | 没有128循环；约束是原始绝对生命周期≤300s、每帧≤500ms、单调 checked request id。 |
| 生产 Trainer readonly、Candidate、Material command | 自己的原连接明确128；不可把 Material command 的上限移植到 legacy evidence/source。 |

B 的内部展开已经从实际 B 请求替换计算，**没有把旧106再相加**。暂停草稿 f5ebe 的106/32/616均只保留历史。

## 较完整的条件式账本

AUDIT.json 列出实际 Version lifecycle 的每次读取。限定单次 Fresh publication、一次真实 issuer、一次 C config 消耗、各一次 S/C factory 与 readiness 服务、没有额外外部观察时，静态展开为：

- resident Evaluation 次数 b = 11 + 2R；
- Version 自身 T/B pairs = 40 + 2R；
- S/C 命令扩张的 T/B pairs = 30 + 8R；
- Q = 70 + 10R；原 B host 总请求 = b + Q；
- 如果全部 T 端点最终回到一个 SourceBoundStage，且 B 通过原 shared factory 绑定 m 个成员，则底层每条 E/D（远端 Material 同数）需求为 `(16m+18)b + (16m+4)Q + 2P`。

m=2、R=0、P=1 时该条件式 core 为3072；这是**指定拓扑下的静态展开，尚未含 setup、未获独立算式复核、不是执行记录或新374结论**。若 B 是独立 fixture Trainer，这条展开不适用；相应 core 要从不经过 Source 的 B 项剔除。详细逐项假设和来源都在 JSON，不给任意外部观察下的全局有限上界。

Progress 和未就绪 readiness 消耗各自连接帧／时间；它们不每轮重新执行 T/B。Version Prepare→progress→完整 readback 的原 reserve 与 C readiness 的原128循环均必须保留。不能用帧数推断某次500ms期限的真实耗时。

## 下一步的工程要求

新374已有 B 同调用证明，先忠实合并并重新展开。若仍超过预算，应让同一次原 owner 验证向上返回实际观察到的完整签名／快照集合，消除同一次调用内部的重复前缀重建；保持所有原前后 Source、native/Generator、member journal、CURRENT 与签名时间检查。私有证明必须绑定原 owner、原连接、scope、nonce、完整 cut 和本次生命周期，不能跨调用缓存 CURRENT，不能把 readonly 变成 Fresh，也不能只增加 cap。

作用范围要覆盖完整 Version / FinalUse / S / C / Root 链，并避免持 Trainer lane 后又经 B 递归请求同一 lane 的锁循环。先保留原失败、原方法与反例，再用每条真实连接的终态／计数验证。当前科学结论仍 HOLD，owner_decision=null。

## 证据完整性

已完整读取并以原始 UTF-8 字节重算 92 个源码 blob 的 Git SHA-1 和 SHA-256，全部匹配固定 src tree。这里没有 actor、编译、测试、手工 Bazel 或 ref 更新。JSON 的 source_pins 是可逐字回读的原件索引；本目录仅文档。
