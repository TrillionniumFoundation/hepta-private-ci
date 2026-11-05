# V15：经控制器中继的两主机生命周期验证

本目录记录一次已经完成的有限协议实验：在两个已配置且经过 SSH 认证的主机 `mac` 和 `pocket4` 上，使用内容完全相同的 V15 `authority.py`，验证组件保存、不同进程冷读取、实际整数矩阵计算、签名迁移和迁移后写入。权威数据库一直位于 `mac`；组件和签名请求经控制器中继，没有直接点对点连接。

这不是原生 Rust 集成、语言效果实验、完整 V15 套件的 Python 3.9 兼容性认证、复制共识或产品收益证明。worker 中的 gate 仅接受明确标识的协议夹具，不运行完整准确率、保持率和成本准入。矩阵 bias 的修改只验证新模型版本确实影响计算，没有“修改后更好”的质量标签。

## 文件与身份

- `host_worker.py`：本次两端实际运行的分阶段脚本，SHA256 `e71df378426d8eb6c7afd8e75938741943fbdb482ec15de17c45b3f74ca12160`。
- `export_requests.py`：链末实际运行的只读 SQLite 请求导出脚本；不读取任何 key 文件。
- `receipts.json`：原始非敏感 stdout、stderr、runtime job 身份、退出状态、输入和签名结果。最后一阶段保留数据库里的六个成功 signed request 及一个被拒绝 signed request，可离线重算所有对应 command hash。
- `costs.json`：由 receipt 派生的逐阶段成本观察与缺失项，不将缺失成本视为零。
- `verify_receipts.py`、`review_checks.json`、`REVIEW.md`：独立离线验签、组件与计算核对及审查范围；不再次操作远端主机。

两端逐进程检查的 authority SHA256 为 `7e5a2016347718e87df147f2ae96f2e56b9813d2c11e705bf88c8649a16bbe68`，与已发布的 V15 源文件一致。原有八个 Python 文件未修改。本次 run ID 为 `hepta-v15-23f86845405a4bb8`。

| 主机别名 | 本轮角色 | 平台 / 架构 | Python | cryptography | SQLite |
|---|---|---|---|---|---|
| mac | 唯一权威及初始 owner | Darwin / arm64 | 3.9.6 | 46.0.5 | 3.51.0 |
| pocket4 | 接收组件、冷计算及新 owner | Linux / x86_64 | 3.14.4 | 46.0.5 | 3.46.1 |
| x230 | 只读能力探测，没有参与迁移 | Linux / x86_64 | 3.12.3 | 41.0.7 | 3.45.1 |

这些身份由配置别名、SSH 认证、观察到的平台信息和本轮 node digest 关联。node digest 是关联标识，不是硬件证明，也不证明同一平台配置对应某一物理设备型号。

## 实际完成的链

两端 setup 各生成自己的随机 Ed25519 key，目录权限为 `0700`，key 文件权限为 `0600`。本执行路径只输出公钥和签名，没有导出私钥；不声称这些文件不可被有权限的管理员导出。

| 阶段 | 执行位置 | 已观察结果 |
|---|---|---|
| setup × 2 | mac、pocket4 | 各自创建独立临时目录，复制原 authority bytes，验证摘要并生成本机 key |
| bootstrap | mac | 创建来源和 epoch 1 cell；源 owner 签名 prepare，事务冻结为 epoch 2 |
| persist | pocket4 | 验证源签名、权威回执及全部组件摘要；文件和目录 `fsync`；进程成功结束 |
| cold_ready | pocket4 | 新进程从磁盘读取 model、memory，实际计算；签名 ready 与 commit 请求 |
| accept_ready | mac | 新进程从持久 prepared 状态恢复，接受目标签名及实际 bytes，持久化 ready |
| commit | mac | 另一新进程从 ready 恢复，提交目标 owner，推进 epoch 3；旧 owner 使用当前 epoch 3 写入被拒绝 |
| sign_publish | pocket4 | 验证权威 commit，签署模型 bias 改变后的新 bundle |
| accept_publish | mac | 验证新 owner 的请求并发布 epoch 4；计算更新后的输出 |
| export_requests | mac | 只读导出本次成功与拒绝的原签名请求，补齐离线证据链 |

本轮十个阶段 job 均退出为 `0`，都具有终态；此前三个能力探测 job 也成功。`persist` 与 `cold_ready` 是两个不同的 runtime job 和 OS 进程，而非同进程重新反序列化。源与目标分别执行的是从实际 model 和 memory bytes 解析出的计算：

```text
源 / 目标冷恢复：[[11, 10], [1, -10], [14, 22]]
修改 bias 后：   [[13, 10], [3, -10], [16, 22]]
```

输入包含三个二维整数向量，模型包含两行整数权重和 bias。其他必需组件槽使用明确标记的未训练夹具内容。完整组件逻辑长度合计 408 bytes，bundle JSON 为 2,276 bytes，首次 persist 请求 JSON 为 3,632 bytes；它们不是网络 wire bytes、完整部署字节或全部持久化存储量。

旧 owner 拒绝证明包括原始 signed request：其 epoch 为提交后的当前值 3，expected bundle 也仍是当时的当前 bundle，因此这里观察的是 owner 隔离，不只是旧 epoch 的拒绝。权威回执原因是 `not current owner`。

## 复现步骤

先离线核验已保存材料：

```bash
python qualification/memory-cell-v15/device_qualification/verify_receipts.py
```

输出为JSON；任何签名、身份、组件、计算、状态或成本绑定检查失败都会以非零退出。

需要两个已授权主机，已有 Python 3、cryptography 以及可用的临时目录；本次没有安装依赖或修改配置。以 HeptaRuntime `process_start` 作为传输入口，始终使用绝对 executable `/usr/bin/python3`、`-B` 和稳定幂等键。用 `process_status` 获取终态，`process_read` 按独立 stdout / stderr offset 分页读到 EOF，不从 launch 成功推断执行成功。

1. 为新实验生成新的 `hepta-v15-` 加 16 位小写十六进制 run ID。不要复用本轮目录或幂等键。读取本目录 `host_worker.py` 与上一级 `authority.py` 的 bytes，计算 SHA256 并 base64 编码。
2. 在源和目标各启动 `python3 -B -c <host_worker.py 原文> setup`，cwd 为通用临时目录。stdin JSON 包含 `run_id`、`role`（`source` 或 `target`）、`authority_base64`、`authority_sha256`、`host_worker_base64`、`host_worker_sha256`。脚本只创建新的 `/tmp/<run_id>-<role>`；目录已经存在时失败，不覆盖。记录返回公钥与文件权限。
3. 后续运行该目录中的 `host_worker.py <step>`，cwd 使用对应新目录，stdin 为该阶段 JSON。每个阶段使用新的稳定 runtime 幂等键；只有相同参数的恢复查询才复用原键。
4. 严格依下表转交 JSON。每个成功阶段读取完整终态和 stdout 后才启动依赖它的下一阶段。

| 下一阶段 | stdin 的来源 |
|---|---|
| source `bootstrap` | `target_public` = target setup 返回的 owner 公钥 |
| target `persist` | bootstrap 的 `bundle`、`prepare_request`、`prepare_receipt`、`authority_public`、`source_public` |
| target `cold_ready` | `{}`；所有 model / memory 均由脚本从本地持久文件读取 |
| source `accept_ready` | `request` = cold_ready 的 `ready_request`；先比较 cold_result 与源结果 |
| source `commit` | `request` = cold_ready 的 `commit_request` |
| target `sign_publish` | `commit_receipt` = commit 返回的权威回执 |
| source `accept_publish` | `request` = sign_publish 返回的目标签名请求 |
| source 只读导出 | 在源临时目录执行 `python3 -B -c <export_requests.py 原文>` |

新运行会产生不同随机 key、请求签名和 bundle ID；应核验身份链、摘要、状态和计算结果，不要求复制本轮签名字节。迁移的所有网络传递均通过控制器 relay。本脚本不创建网络监听器或永久服务。临时工作目录可保留用于复查，生命周期与清理由操作方管理。

## 失败与测量边界

最初对三个主机使用相对 executable `python3` 的请求均被入口以 `INVALID_ARGUMENT` 拒绝，未生成目标 job；随后使用显式绝对路径作为新的、不同幂等键的请求。三次失败均保留，没有覆盖成成功。还有一次本地证据文件的补丁写法被 `apply_patch` 拒绝；这没有远端协议效果，没有重复远端动作，也被保留。十个已启动协议 / 导出阶段没有失败。

`process_elapsed_s` 的计时起点在 Python imports 之后，因此不包含解释器启动、库导入和控制器传输。user / system CPU 则是进程生命周期的累计计数；RSS 是单进程峰值，不能将不同主机或阶段的峰值相加当成系统总 RAM。`controller_start_elapsed_ms` 是 process_start API 往返，不是纯网络 RTT，也不是应用完整端到端延迟。

能源、网络 wire 流量、物理存储占用、整机总内存、完整训练摊销和完整生命周期成本均未测得，在 `costs.json` 保留 `null`。初始失败和基础设施操作的完整成本也未知。本轮没有训练，并未比较相同预算下的学习效果或收益，因此不能据这些控制测试认定产品净收益。

本证据没有覆盖断电、磁盘硬件失效、远端保留时长、拜占庭接收者、独立见证、权威整盘回退、跨主机 SQLite 共享存储、共识恢复或网络分区自动接管。目标签名加上本轮成功的文件落盘和不同进程冷计算，加强了此次观察的证据；它没有把 ready 升格为任意远端未来持久性的证明。

## Historical and current source identity

The recorded Mac-to-pocket4 execution remains bound to executable source
`386f7a4453b5e59e83db12d8bf958cfb5e4847d0`, preserved by
`379c21c2e625c3a3dfbb514e11b9e8fe2213cda8`. Its signed receipts and costs have
not been edited. `history/manifest.json` pins their hashes, the original independent
CI receipt and all eleven source objects in `history/sources.zip`. The verifier
checks each file's SHA-256, byte count and original Git blob identity, reads the
archive as data, and never imports or executes the archived implementation.

Current `evidence/checks.json` is a separate qualification record. It must report
passing unchanged source and exactly cover the current top-level Python inventory;
every current source hash is still checked. The output reports the historical
authority/source identities and current protocol-check identities separately.
A successful historical verification does not qualify current device code or count
as another device experiment. Changing the authority for the epoch fix or later
admission changes therefore cannot relabel the older Mac-to-pocket4 execution.

This corrects the observed CI run
[41981272551](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/41981272551),
which passed 57 protocol cases but failed `authority source identity mismatch` when
the newly generated checks were compared to the older device receipt. Its subsequent
native steps were skipped; that original failure remains part of the record.

Run the regression controls separately from the original protocol suite:

```bash
python qualification/memory-cell-v15/device_qualification/history_tests.py
python qualification/memory-cell-v15/verify.py
python qualification/memory-cell-v15/device_qualification/verify_receipts.py
```

The controls run the actual protocol suite on a newly identified source copy, verify
that the old device record remains attributed to its old source, and require refusal
for altered historical bytes/manifests/receipts and unqualified current source edits.
