# B16 基础阶段：最终 A 绑定清单

本文件是 V3 runner 的独立准备收据，**没有启动 B，没有修改冻结 runner 或产品源码**。这里只准备 `B16/phase/B01–B10`，这些内部编号不代表原 blocker 账本的 B01–B10。

## 已固定与待固定

现成 fb9 完整 selection 原件为 5,364,870 字节，SHA-256 `48dcb2b104793c7dac9699803e4746d6d8145bcc66701de167de57cbf6bd3c6c`。321 个实际测试程序共 15,300,982,712 字节，33 个实际 helper 共 2,822,015,256 字节，354 个独立文件合计 **18,122,997,968 字节**。这是文件大小观察，不能当作整个 target 的占用或构建峰值。

`last_tested_A_tree` 可固定为 `fb9e131272f7e7a138d6c0d1af2b048b9a6ab7ff`。`final_A_tree` 必须等 A 最后的 fix/fmt 与完整源审查。原 ordinary index 曾受 Python/Git 步骤影响，因此索引、HEAD、两把锁和完整 metadata 都必须从最终状态重新绑定；不能把 fb9 旧产物改标签说成 final A 测过。

基础阶段有 16 个路径，7 个要求既有精确 blob，9 个要求原路径不存在。全部在 last-tested fb9 上已用真实 crate subtree 身份与冻结 payload 对齐，但最终 A 仍须再次核对。逐文件 pre/post 和 absent 要求已列入 JSON；任何不符必须停止并审新 delta。

## 这一个 epoch 的范围

保持原 24 个不同正向用例、27 次正向执行（codec 前 3 个在后续 7 例中重复）及 10 次精确反事实；保持真实 SQLite、物理锁、原时间预算、0 retry、完整 JUnit 与 finally 精确恢复。先完成 foundation，再引入 native lifetime token。基础阶段不改 Cargo/BUILD 或两把锁，不进行 Bazel 生成、build 或 test；既有 runner 的 Bazel 版本校验仍保留。

每个 scope 仍实际构建 6 个 normal helpers，并运行完整 workspace metadata/catalog，然后精确核对来自 fb9 的完整 33 个 basename 清单，重新记录当前程序与 helper 字节。共用 target 不构成借用旧产物资格。

## 单阶段容量提案

| 项目 | 字节 |
| --- | ---: |
| 额外一个实际已观测 executable family | 18,122,997,968 |
| 其他 Cargo 增长估计 | 12,000,000,000 |
| foundation 的 Bazel 增长 | 0 |
| evidence 增长估计 | 2,000,000,000 |
| 原保留余量 | 8,000,000,000 |
| **规划所需 free** | **40,122,997,968** |
| Root 给出的实际 free 观察 | 47,045,021,696 |
| 仅按以上数字的余量 | 6,922,023,728 |

Root 的 free 是十进制 47.045 GB；作者尚未独立重读其 host 收据。这个估算不是峰值实证，也不是启动许可。实际启动前必须重新读取同一文件系统 free，并由 Root 明确接受本 epoch 的估算。原 8 GB 检查不变、不删 cache、不减少 scope；命令前后检查也不能保证编译进行中绝不跌破余量。

driver 阶段会新增依赖和真实 Bazel 生成，必须依据 foundation 真实终态重新评估。如仍套用旧 8 GB Bazel 估计，总要求会回到 48,122,997,968 字节，超过这次报告的 free，不能将 foundation 的预算许可外推。

## 可交接入口

`foundation-binding-UNBOUND.json` 仅预填真实 fb9 selection 哈希、33 个 helper basename 和待审容量提案；`execute=false`，最终 A、索引、锁、metadata、路径及审批引用仍为空。它不能启动 runner。实际执行仍由唯一 native executor 在 Root 的独立 source guard 后进行：`python3 b16_runner.py --binding <reviewed-binding> --epoch foundation`。

完整逐项检查和 exact stage 名单见 `foundation-readiness.json`。V3 runner、原始 42 个对象及 V1/V2 历史保留，本次不改变 B16 或原 23 项 blocker 的退出条件。
