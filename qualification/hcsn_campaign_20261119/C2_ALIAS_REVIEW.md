# C2 exact-initial alias 恢复：独立只读审查

日期：2026-11-19。审查者：独立代理 `/root/n256_closure`。

本记录核验三项 initial 路径恢复的冻结入口、前驱原件绑定和预算延续。
审查未修改 C2 源码或原件，未导入 Torch、构建模型、运行 forward、测试或训练。
实际操作仅为源码读取、Git 身份核对、JSON/base64 解码和文件哈希检查。

**结论：未发现需要暂停该冻结 alias 恢复入口的阻塞问题。**
这项结论不代表后续三个 forward 已通过，也不预先认可它们随后可能遇到的
checkpoint 语义差异。后续执行结果必须按各自原件另行报告。

## 1. 冻结身份

审查的远端提交为
[`9d4366cba399dff877879cc8f6ac03e0f3a1ba67`](https://github.com/TrillionniumFoundation/hepta-private-ci/commit/9d4366cba399dff877879cc8f6ac03e0f3a1ba67)。
GitHub GET commit 和本地 Git 均给出完整 tree
`29568558579b1dfee241c753153ca99b43b911f5`。
本地对应提交为 `646d6971351d9dbc39fb47b327fcc58a2f111681`。

本地审查目录：
`/workspace/scratch/2f21518ff984/c2-temperature/qualification/hcsn_c2_D_path_reconciliation_20261119`。

| 文件 | SHA-256 |
| --- | --- |
| `SOURCE_FREEZE.json` | `13865227a0082f2c748de86315166a03041015541e2df2de0499e36e52a479c5` |
| `REQUEST.json` | `0b4bebb48f84438c2ad75e1e908e65ab5118b5076b5f6fe029e8560c1ea0971a` |
| `PREDECESSOR_SOURCE_FREEZE.json` | `3d1fc074c619cb11beafc765a472ccaed7ed0f41b8ce32611feb73fa71e5cb9f` |
| `PREDECESSOR_REQUEST.json` | `65866ce7122d3822966a660353dd992f9655c6f982daef7ccf6c5798f5522ee5` |
| `reconcile_paths.py` | `edab916825ff907d1d780661553ac5a128d2cd5342df914a6836d785246bf1d8` |
| `replay.py` | `99cbf1cb15143d6cc48ce4f377f98049667f2247198e42a5e1b193ab71ac6a8e` |

全部 20 个 source-freeze 条目均经独立哈希核对。`replay.py` 与前驱执行版本
逐字节相同；复制的前驱 request 的 SHA 与前驱 source freeze 中的绑定相同。
前驱冻结提交为 `6e53707e317f6d0a12d5402ac9dd14c26dc3ae4c`。

## 2. 三项 alias 的严格范围

原 native campaign 根目录为
`/home/qian-qi/hepta-hcsn-core-study-20261110-c385-training/campaign-v2`。
下表路径均相对于该目录，每个 initial 文件保持原声明大小 154,078 bytes。

| 待完成的 fit | 原 initial 路径 | 绑定的存活 initial 路径 | 原 SHA-256（保持不变） |
| --- | --- | --- | --- |
| `hcsn-s101-lr0.003` | `hcsn-s101-lr0.003/initial.pt` | `hcsn-s101-lr0.001/initial.pt` | `abecac574f221f7617e59514f95d3703bcf1efbd43afc3086e18bf2b5eb8a0c2` |
| `hcsn-s211-lr0.001` | `hcsn-s211-lr0.001/initial.pt` | `hcsn-s211-lr0.003/initial.pt` | `143cfe696633a7e73dd3c2f3ac9600ae30ce8ea263f5c19a3efed3f9221f6552` |
| `hcsn-s307-lr0.001` | `hcsn-s307-lr0.001/initial.pt` | `hcsn-s307-lr0.003/initial.pt` | `9b3821159fdcb47bbb40af4dcda89daa87fa1bef85b3bf675b0af860a4f4faa7` |

逐行比较新旧 request：只有 `initial.path` 改变；initial 的 SHA/bytes 及其他
所有字段完全相同，包括 checkpoint、D logits、模型配置、strict-best 选择、
数据和 dependency source map。runtime、limits 和 source aliases 也保持原值。
恢复不是重新选择 seed、LR、epoch、模型或参数。

driver 在任何补执行之前要求替代文件 SHA 等于原冻结 initial SHA。
原 `replay.py` 继续要求输入为常规文件且不是 symlink，并在执行后检查输入哈希。
本审查核对了这些强制条件与冻结 SHA；替代 native 文件的实时读取由该冻结
driver 执行，本审查没有把本地不存在的 native 路径当作已亲自读取的文件。

## 3. 前驱原件与零 forward 失败的核对

前驱 native 根目录为
`/home/qian-qi/hepta-c2-current-D-replay-20261119-2f215`，job ID 为
`1a1f3ec2f5e-ffbe-e7f`。绑定的 native 回执确认终态 `failed`、exit code 2、
`terminal_publication_confirmed=true`。这只是该次新 replay job 的终态，
没有据此改写更早 C2 controller 的历史 `UNKNOWN`。

独立读取的十份前驱原字节容器为
`/workspace/scratch/2f21518ff984/current-D-predecessor-bindings.json`，SHA-256：
`eea5acbb279f0504201d043c7451a14302420c05598061bfb899ac321a1a7aa4`。
它包含 source freeze、SUMMARY、ARCHIVE、三个失败 RESULT、三个单项 COST
以及 partial-chain COST。

审查逐份 base64 解码并核对 offset=0、EOF、next_offset、size、chunk SHA
及新 request 的 SHA；十份全部吻合。三个单项 COST 与 SUMMARY 中对应行
完全相同，前驱 SUMMARY 记录 3/6 成功。

三个失败 traceback 均明确指向原 initial 路径的 `bound input identity`
检查。冻结代码中该检查先于任何 Torch import、模型构造与 forward；失败
RESULT 中没有 `runtime` 或 `best_epoch`，保留零 backward/optimizer/update。
新 driver 还要求旧 fit 目录没有 `BATCHES.jsonl`、`INPUTS_BEFORE.json` 或
`FRESH_D_LOGITS.pt`，若观察到任何这些文件便拒绝补执行。

原三个成功 fit（`s101/.001`、`s211/.003`、`s307/.003`）不在新 roster。
后续覆盖率应由三个原成功项与三个补首次 forward 的独立结果合成，不能写为
重新运行六项。原输出目录不被覆盖；新目录与 archive 的写入使用禁止覆盖模式。

## 4. 原预算的扣除和同一绝对截止时间

原单项预算 210 秒、metadata 预算 360 秒、全阶段预算 1,800 秒保持不变。
扣除的是父进程 `wait4` 计量的完整 child 壁时，而不是较小的内部 body 时间。

| Stage | 前驱已耗 full-child wall 秒 | 扣除后的最大剩余 stage 秒 |
| --- | ---: | ---: |
| `hcsn-s101-lr0.003` | 0.20168612501583993 | 209.79831387498416 |
| `hcsn-s211-lr0.001` | 0.20160499104531482 | 209.79839500895469 |
| `hcsn-s307-lr0.001` | 0.6022693830309436 | 209.39773061696906 |
| `partial-chain` | 13.722937767975964 | 346.27706223202404 |

原绝对 deadline 是 Unix `1795095504.542`，原 native creation 对应
`1795093704.542`。每个 stage 实际 grant 为：

`min(扣账后的 stage 额度, 1795095504.542 - time.time() - 60)`。

grant 非正即记为原预算耗尽，不启动子进程。监控沿用 `wait4` 和超时终止，
保存新 child 完整 wall/CPU/RSS 与前驱已耗 wall；最终再检查同一绝对 deadline。
新 job 的启动没有重置科学总时钟，归档仍留在该 deadline 内。
实际最终是否在各预算内完成，应以新执行 COST 和终态回执确认。

## 5. 保留的科学边界

此次入口只允许同原字节 initial 的路径解析恢复。它不放宽 checkpoint 的
epoch/config/data 语义门、logit/metric 阈值或原训练资格；后续语义失败必须
先逐字段定位并另行冻结可证明的适配，不能由本审查自动授予豁免。

`E_access=false`、`original_controller_terminal=UNKNOWN`、原完整训练 replay
`0/6`、`original_full_C2_chain_auditor_completed=false` 和
`scientific_admission=HOLD` 均保留。原失败与两阶段全部费用不得删除或退款。
