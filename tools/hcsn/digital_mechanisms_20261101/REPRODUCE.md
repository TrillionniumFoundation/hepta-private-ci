# 归档清单与复现

[ARCHIVE_PUBLICATION_INDEX.json](evidence/ARCHIVE_PUBLICATION_INDEX.json) 是本轮归档的逐文件入口：列出每份 manifest、文件索引页、base64 分片及传输侧记的相对路径、字节数、SHA256 和 Git blob SHA1，并记录覆盖范围及已完成的恢复验证。本索引核对本地文件；远端是否全部发布，以另存的逐 blob 核对记录为准。

当前共有 **30 份归档、861 个分片、127 页原始文件索引**，覆盖 **56,874 个归档成员、422,074,327 个逻辑字节**；拼接后的 gzip 共 284,676,921 字节。逻辑总量按成员文件长度求和，包含有意保留的重复证据和探针中的嵌套归档，不等于去重数据量、独立样本数或磁盘块占用。30 份归档及其 16 份确认传输侧记共 1,034 个发布文件。

## 覆盖范围

下表名称均对应 `archives/名称/名称.manifest.json`；每个确认 fit 有自己的 manifest。

| 归档名称 | 原始文件数 | 逻辑字节 | 内容 |
|---|---:|---:|---|
| `development` | 2,390 | 9,461,014 | DEV 101/103/107 的首次失败尝试、部分产物、stderr 和非零进程回执 |
| `development_source_v1_exact` | 35 | 674,761 | 上述尝试的精确源码及依赖快照 |
| `development_v2` | 2,531 | 23,313,953 | 相同 DEV seeds 的成功修复重跑 |
| `development_source_v2` | 36 | 681,864 | 修复版本的精确源码及依赖快照 |
| `smoke` | 1 | 478,294 | 实际读取、训练及执行 smoke 的保留结果 |
| `formal_first8` | 6,733 | 42,503,993 | 前八个正式 fit 的训练数据、192 个模型及完整进程回执 |
| `formal_second8` | 6,719 | 42,155,645 | 后八个正式 fit 的训练数据、192 个模型及完整进程回执 |
| `confirmation_fit_ID`，共 16 份 | 22,505 | 235,880,485 | 每个 fit 的 IID/OOD 任务数据、评估记录及匹配进程回执 |
| `native_confirmation` | 2,201 | 1,986,626 | 冻结参数原生实验的可执行文件、编译记录、全部 checkpoint、事件及进程记录 |
| `native_outer` | 4 | 5,518 | 原生实验完整进程 CPU 回执和输出 |
| `trained_retention` | 21 | 372,214 | 16 个冻结 fit 的注册次级保持探针 |
| `actual_readout` | 33 | 3,182,789 | 16 个 fit 的事后 readout 审计、源码快照、DEV replay 和执行回执 |
| `wait4_accounting` | 5 | 2,751 | 完整进程及后代 CPU 记账探针 |
| `stream_archive_probe` | 13,435 | 58,254,906 | helper 的全部验证尝试，包括最初 harness 计数错误、损坏/截断输入和部分恢复产物 |
| `transport` | 225 | 3,119,514 | 冻结时刻的传输回执、watcher 源码与日志、旧证据保管说明和探针传输记录 |

正式 fit 顺序为 `501 503 509 521 523 541 547 557 563 569 571 577 587 593 599 601`。`formal_first8` 与 `formal_second8` 分别覆盖这一顺序的前八个、后八个 fit；合计 384 个训练模型，身份由 [SEALED_MODEL_FREEZE.json](SEALED_MODEL_FREEZE.json) 绑定。

首次 DEV 的三个进程均返回 1；修复重跑三个进程均返回 0。失败记录属于开发成本与开发证据，不能将重跑解释为新独立确认。保持探针及事后 readout 的解释边界见各自报告，不能替代预注册主终点。

## 从原始字节恢复

归档恢复只需 Python 3.12 标准库。以下示例从仓库根目录运行；目标目录必须尚不存在，且应先确认可用空间足够：

```bash
python3.12 tools/hcsn/digital_mechanisms_20261101/orchestration/stream_archives.py restore \
  --source tools/hcsn/digital_mechanisms_20261101/archives/formal_first8/formal_first8.manifest.json \
  --destination /tmp/digital-reproduction/formal_first8
```

其余归档使用索引中各 `manifest.path`，每份恢复到独立的新目录。helper 会核对所有分片、索引页、成员长度及 SHA256，检查 gzip EOF/CRC 和 tar 结束块，并拒绝不安全或重复成员。无需重新训练或执行确认任务即可恢复本轮保留字节。若要运行新的训练实验，依照 [README.md](README.md) 的 TRAIN/validation、源码冻结、模型冻结、发布核对和确认顺序，使用新的输出目录；按实际 CPU 时间停止的训练在不同主机上不保证得到相同更新数和权重。

归档保留普通文件字节，不恢复原始文件时间戳；时间先后以原始回执中的显式 UTC 为准。绝对路径是历史执行记录，复现时使用恢复后的相对布局。探针的空目录清单保留在 `transport` 中的 `stream_archive_probe_inventory.json`；它与普通文件归档共同记录完整目录拓扑。

## 传输快照、回收与证据边界

`transport` 保持 **225 文件**的原始密封快照。之后增加的 **6 个** `actual_readout_{pack,restore}.{json,stdout,stderr}` 文件单独保留在 [evidence/operational/transport_after_closure](evidence/operational/transport_after_closure)。该快照自己的 **15 个**外层、pack/restore 回执及 inventory 单独保留在 [evidence/final_transport_outer](evidence/final_transport_outer)，避免递归包含自身。完整外层 `wait4` 与内部候选/子进程计时是嵌套范围，不能相加。

[DUPLICATE_RESTORE_CLEANUP.json](evidence/operational/DUPLICATE_RESTORE_CLEANUP.json) 记录磁盘空间不足后的可重建副本回收范围：19 个恢复副本，49,409 个已与原始文件逐字节比较的文件，共 405,199,761 个逻辑字节。原始证据和归档保留；复现不要求那些临时恢复目录继续存在，也不以目录当前是否消失替代原始恢复验证回执。本次编制索引没有新增恢复操作。

旧数值/原生验证对应预格式化 Rust SHA256 `d37e25193c318a34f6e79a025b0661c23147a9af840bfcc3bfaa7cfc33cb80ef`。保留 JSON 包括数值汇总、12 个最终 checkpoint、22 条事件记录、上下文切换记录及拒绝信息；旧可执行文件字节、原始逐进程 stdout/stderr、中间 checkpoint 和逐路径 Monte Carlo 数组未完整留存，见 [OLD_RENEWAL_CUSTODY.json](evidence/legacy_development/OLD_RENEWAL_CUSTODY.json)。这不是完整旧 raw archive。

新的 `native_confirmation` 对应当前 Rust SHA256 `64df3f47465ba0d66451830e8cc845339b8dd67fedd64727b14fab5ca988f2fc`，独立保留 128 个冻结参数案例、384 个实际轨迹进程的原始证据。它验证的是单独有限 CTMC 的事件及恢复接口，不意味着生产 owner 集成、连续 Brownian 空间收敛或神经策略效用已经通过验证。
