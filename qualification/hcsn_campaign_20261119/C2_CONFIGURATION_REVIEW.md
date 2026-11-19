# C2 continuation 配置缺项：独立只读适配审查

日期：2026-11-19。审查者：独立代理 `/root/n256_closure`。

**结论：已有原字节证据支持严格补全两项缺失的 expected configuration；
最终冻结适配保持原 checkpoint 语义门与原预算。未发现入口阻塞问题。**

本记录审查的是缺项来源、身份链、代码约束和预算扣账，不提前宣称后续两个
full-D forward 或整个 native job 成功。审查没有修改 C2 源码/原件，没有导入
Torch、构建模型或运行 forward、backward、optimizer。只执行了文件读取、
Git 核对、stdlib JSON/base64/hash 检查与纯字典字段比较。
先前的 `C2_ALIAS_REVIEW.md` 原字节保持不变。

## 1. 最终冻结身份

最终远端 source commit：
[`6665a66ebdae1224d8a6bac4f22c0878136b33f7`](https://github.com/TrillionniumFoundation/hepta-private-ci/commit/6665a66ebdae1224d8a6bac4f22c0878136b33f7)。
GitHub GET commit 核验的 tree 为 `7ccc4c5803e40c79ec43cae320b9fa19d29c6c01`，
与本地 `56d48b2566702cc4dfe3cbf144bb0ce529717fbc` 的 tree 完全一致。

本地审查目录：
`/workspace/scratch/2f21518ff984/c2-temperature/qualification/hcsn_c2_D_configuration_reconciliation_20261119`。

| 文件 | SHA-256 |
| --- | --- |
| `SOURCE_FREEZE.json` | `f844d88c740b50a2d26b3c79246243a0eecd9c7b79d0bce883e0688fef7f3678` |
| `REQUEST.json` | `c9ee57489f348e71fe8cda0a51f9f8d14e722c1930900ad8b5c08dc4712e0aba` |
| `CONFIGURATION_ADAPTER.json` | `b76aa9979a1c9244b11445d4f159a06e1ded6729efeb14491ad440100c29bcf9` |
| `reconcile_configuration.py` | `d2a4467827f9af1450992396a4562b3bcc5075815c384e93159c66c399d9651f` |
| `validate_configuration.py` | `f89d122022df80940d60858873cd71ab286abbd5460932d8b726e89a0ac7aa10` |
| `replay.py` | `99cbf1cb15143d6cc48ce4f377f98049667f2247198e42a5e1b193ab71ac6a8e` |

31 个 source-freeze 条目全部独立核对通过。`replay.py` 保持前两阶段的原字节，
包括完整 epoch/configuration/data 等式、原 logit/metric 阈值及输入前后检查。

## 2. 精确根因：候选索引遗漏赋值

原 `qualification/hcsn_c2_d_selection_20261119/build_selection.py` 的 SHA-256
为 `3a1544d8a64b25e8de55a20854bb5d8db45d750e247697e28a3142f9b847f19a`。
该程序对每个候选先置 `config=None`。`independent_continuation` 分支更新了
checkpoint、logits、metrics、adequacy、report 和 cost，却没有赋值 config。
因此 `SELECTION.json` 的 `all_42_candidates` 中两条 continuation `.001`
记录保存了 `model_configuration=null`。

两条缺项记录分别是 `hcsn-s211-lr0.001` 和 `hcsn-s307-lr0.001`。原选定的
三个 HCSN winners 都是 `.003`；本次补全不改变 common-LR 选择、strict-best
epoch、checkpoint、D logits 或开发集分数。原缺项与失败请求继续保留。

只读 metadata 诊断原件 `SEMANTICS_DIAGNOSTIC.json` 的 SHA-256 为
`3e85975acd1661ad65569b277c7bce4951fa81a54e2fda82d6dcde7646a3481f`，
大小 1,849 bytes。实际字段为：

| 候选 | 实际/原期望 epoch | 原 checkpoint SHA-256 |
| --- | ---: | --- |
| `hcsn-s211-lr0.001` | 144 / 144 | `83f7b3148c10fa377feb9f4449ffa42a0b1679f073569f1886852d7eb82145c3` |
| `hcsn-s307-lr0.001` | 126 / 126 | `14a9c527bf87ad6524c771ab7da5a1ccf32723cd1f2fc6c7d8f6d8797d1b2ed9` |

两者实际和原期望 data manifest 都是
`0eb233da8d0b766c35356ba450d0572f1e6a87a47f1d8a17cd32c2ae6f25a1cb`。
实际 configuration 是完整字典，原期望值为 null。这里是声明缺失，不能把
null 当作另一种有效配置，也不能直接从待验 checkpoint 抄写 expected 值。

第二阶段六份结果/成本/汇总/归档回执及两份原 plan 的读取容器为
`/workspace/scratch/2f21518ff984/configuration-adapter-inputs.json`，
11,430 bytes，SHA-256
`006ec20c04f320278bdf139bbc6d2b15e81cf2aad145e143bbe55ee163bb6912`。
全部八份回执逐一解码核对 offset=0、EOF、size、chunk SHA；六份 alias 输出
也与最终 request 的绑定一致。两个新失败 trace 都止于 checkpoint 语义门，
该门在模型构造之前。它们已导入 Torch 读取 checkpoint，但没有 model/forward。

第二阶段 SUMMARY 新增 `s101/.003` 一项成功，full-child wall 为
126.2002793639549 秒；此前三项成功不重跑，合并覆盖为 4/6。
两个 continuation 语义失败的 return code 都是 2，失败和费用完整保留。

## 3. 独立重建与前置证明链

历史 `ORIGINAL_TERMINAL_SNAPSHOT.json` 的 SHA-256 是
`17df82cc70fce7d42ad1389c5770ba42a8039522ab07f36f6b6403b1d0156c49`。
两份复制的原 parent plan 均为 1,110 bytes，其 SHA 与该历史 snapshot 一致：

| 候选 | 原 parent plan SHA-256 |
| --- | --- |
| `hcsn-s211-lr0.001` | `74a25f964a655a0302440cd431f69a46cd4ea62a056c2282f11547ebbec2d8a7` |
| `hcsn-s307-lr0.001` | `359c278aea86b9d748f95c5b91efb5d5281302405f84ee07d4afbd6ce36e379e` |

审查者使用 stdlib 按原 `audit_io.construction(plan)` 的字段映射独立构造
字典；它与 adapter、最终 request 和只读诊断中的实际 checkpoint 配置逐字段
完全相等。映射保留 arm、width、seed、s4 路径、完整 hcsn_grid、共享参数冻结、
cache、adapter 和 plif 配置；没有忽略路径、舍弃字段或作近似比较。

最终 driver 强制两项原 request 的 configuration 为 null，并只允许该字段
变化，其他每个 fit 字段必须完全相同。它验证原 plan 本地副本、native 路径、
历史 snapshot 和未修改的 construction 源码。

新增 `validate_configuration.py` 在任何补 forward 前运行，强制验证：

1. 原 parent report 的 SHA 等于历史 snapshot 的 `result.json` 身份。
2. report 的 `plan_sha256` 等于原 plan 实际 SHA 和 adapter 的已绑定 SHA。
3. initial 实际 SHA 等于原 report 的 `initialization_sha256` 和冻结 fit SHA。
4. 从原 plan 独立推导的 configuration，精确等于 parent report、initial
   payload 和新 request 中各自的 configuration。
5. 上述输入前后哈希及 source freeze 均保持一致。

证明子进程只读 initial checkpoint metadata，不构造或执行模型。driver 要求
独立输出 `CONFIGURATION_PROOF.json` 存在且状态为 `PASSED`，才允许启动原
`replay.py`。随后原 checkpoint/configuration/data 语义门继续逐项严格比较。
本审查对这一段给出的是源码约束结论；实际证明和 forward 的执行结果应读取
该次 native job 的终态原件，不能由入口审查替代。

## 4. 同一时钟和累计扣账

科学总 deadline 仍为 Unix `1795095504.542`，由原 native creation
`1795093704.542` 起算 1,800 秒。新 native job 不重置该时钟。
两个 fit 同时扣除第一阶段 initial 身份失败和第二阶段语义失败的 full-child
wall 时间；已成功的四项不在新 roster。

| Fit | 第一阶段已耗秒 | 第二阶段已耗秒 | 原 210 秒额度的剩余秒 |
| --- | ---: | ---: | ---: |
| `hcsn-s211-lr0.001` | 0.20160499104531482 | 5.609433618024923 | 204.18896139092976 |
| `hcsn-s307-lr0.001` | 0.6022693830309436 | 5.508869731973391 | 203.88886088499567 |

metadata 原 360 秒额度扣除两个 partial-chain 子进程的
13.722937767975964 与 11.717589066014625 秒，再扣只读诊断的 native
creation-to-terminal 6.838 秒，剩余 327.7214731660094 秒。
没有用诊断较小的内部 body 时间代替其计费区间。

每个实际 stage 仍取 `min(累计扣账后的额度, deadline - now - 60 秒)`；
额度耗尽不启动。完整 child wall/CPU/RSS 留存，归档后再检查原 deadline。
最终预算符合性必须以新 COST 和 native 终态确认，不提前按估计授予通过。

## 5. 结果边界

本适配补全的是原本缺失的独立期望声明，没有替换 checkpoint，没有放宽
语义/数值门，也没有退款前两次失败或改用新科学预算。旧 null 记录、两阶段
失败和原 archive 全部保留。

`E_access=false`、更早 controller 的 `UNKNOWN`、原完整训练 replay `0/6`、
未完成原完整链 auditor 和 `scientific_admission=HOLD` 继续保留。
本记录不把当前 best 的 D replay 等同于完整训练重放或 E 确认结果。
