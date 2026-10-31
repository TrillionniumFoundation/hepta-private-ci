# V12：跨 runner 读回、所有权迁移与撤销的实测证据

## 已完成的结果与待完成的范围

**两次三 VM live workflow 均已完成，全部 artifact 已下载并独立核验通过。** 每次都有三个不同的 kernel boot 与 instance 身份；source 和两个 replica 的服务进程在 prepare、epoch-2 读回、撤销后请求和停止之间保持相同 PID 与完整身份。每次 final 的 10 项检查全部通过，两份 completed 回执均绑定该次实际 final message 的 SHA，并确认自己的新请求被拒绝后才停止。

七 VM 串行 workflow `41157593645` 在本报告 checkpoint 尚未完成：source、两个初次 replica、migration controller 已成功；两个 readback job 排队，final 尚未完成。**不能将三 VM 的成功或七 VM 前四个 job 的成功写成七 VM 完整通过。** 后续收尾须独立保留该 run 的全部阶段、精确源码和审计，不改写这里已完成的三 VM 证据。

| Run / attempt | 精确执行提交 | 当前验收状态 | 原始 artifact |
|---|---|---|---:|
| [41157593644 / 1](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/41157593644) | `024acd29eb46361619f01dcc2782a2ad076bc5e0` | 首轮 live：3/3 jobs 成功，独立核验通过 | 15/15 |
| [41157871480 / 1](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/41157871480) | `ca002c6189ba107077f8ea8e0ea50e2227a3b806` | 加强 envelope 校验后的 live：3/3 jobs 成功，独立核验通过 | 15/15 |
| [41157593645 / 1](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/41157593645) | `024acd29eb46361619f01dcc2782a2ad076bc5e0` | 七 VM 串行：前四 jobs 成功；两 readback queued，final 未完成 | 不作为完整通过 |

`ca002c6` 是提交前缀，表示加强跨 artifact 的 schema、label、binding、executed-source 与 limits 校验的版本；这里没有声称引入了证书机构或新的密码学信任根。两个版本各有自己的运行证据，不能用较早 run 替代较新源码的执行。

## 1．归档与精确身份

可发布的无损归档入口：

- [首轮 live 归档](evidence-packs/federation-live-41157593644/manifest.json)
- [加强校验版 live 归档](evidence-packs/federation-live-41157871480/manifest.json)

每份包含 GitHub artifact 清单及 job 状态、全部原样 ZIP、安全解包文件、原始 SQLite、各阶段消息与服务日志、固定提交取回的实际执行源码、独立采集和核验脚本，以及 `ARCHIVE_VERIFICATION.json`、`INDEPENDENT_AUDIT.json`。原始目录分别为 `evidence/federation-live/run-41157593644/` 与 `evidence/federation-live/run-41157871480/`，可从归档恢复后访问。

两个 run 均独立完成以下完整性检查：

1. 15 个 artifact 的 GitHub `workflow_run.id` 和 `head_sha` 与目标 run/source 一致。
2. 每个原样 ZIP 的字节数及 SHA-256 与 GitHub advertised metadata 一致。
3. 解包前拒绝绝对路径、路径越界、重复成员、链接、特殊文件、加密成员及超预算展开；已有三份首轮下载也逐文件核对为与 ZIP 相同。
4. 12 个协议 message 的 run、attempt、nonce、workflow ref、source binding 一致；三个 diagnostics artifact 另外保留进程和持久化证据。
5. 消息声明的三份执行源码 SHA 与对应固定 Git 提交取回的源码相同。源码快照是在运行后按固定提交取得，报告未把它说成运行前另做的冻结。

两次协议的 final message SHA 分别为：

| Run | Final message SHA-256 |
|---|---|
| 41157593644 | `d95ef3a8d7908e566a25dff3353f526cf67988a30a3d9ad642d3578537702f84` |
| 41157871480 | `78150535d144e99227f9e2b8acc04671c43abafea40edae0df7fc3d3b1a74559` |

每次 replica-a 和 replica-b 的 completed 回执均引用本行对应 SHA；它们不是仅根据一个通用 `passed=true` 标记停止。

## 2．实际迁移的是哪个 learned model

两次 run 都使用 WP2 协议预先选定的 **40 模块、seed 17041、single MLP**，没有在 runner 上生成替代的易任务模型。固定模型文件身份为：

`ead9abe3bfa39654e27e61b883cb3014791b140d1f19c063615b09dda569f361`

固定 probes 文件身份为：

`0824f44e7bdba2a861aeced3a1c3f81ecb6af6c8f1bd4cf8feb650cb3d044839`

模型共有 **17,098 个参数、68,392 B 原始 FP32 权重**；实际 `model.json` 为 138,370 B，`probes.json` 为 17,888 B；加上该 run 绑定的 `bundle.json`，完整 bundle 为 157,044 B。该 serving 模型不含 Adam，**本实验未迁移 optimizer，也没有跨机器继续训练的验收**。

独立核验器不导入 producer 实现，用 stdlib 解码 FP32 字节并按 f64 顺序计算 ReLU 前向，再比较保存的 8 个 probes。两次的最大绝对误差都为 **0**；每个 worker 日志中的实际 compute 输出也与独立重算相同。

这证明固定模型数值在异地读回一致，不证明这些问题的语义答案全部正确。该模型在独立 WP2 held 任务中为 22/80 raw exact、4/80 accepted-correct；迁移对象是协议固定选择，见 [CONTENT_RESULTS.md](CONTENT_RESULTS.md)。8 个一致 probes 不能覆盖或撤销原内容实验的失败。

## 3．三 VM live 链条实际覆盖了什么

同一 workflow 的三个 GitHub-hosted jobs 分别运行 source、replica-a、replica-b。controller 的 SQLite 保持在原 source VM 上，三条长驻服务进程只计算 candidate；candidate 明确带 `serving_authorized=false`，只有受信任的 controller 决定释放。

实际状态依次为：

| 阶段 | Epoch | 逻辑 owner | Checkpoint 有效 | 实际行为 |
|---|---:|---|---:|---|
| 初始 | 1 | source | 1 | 两个 replica 加载同一权重并提交实际计算结果。 |
| 迁移 | 2 | replica-a | 1 | 新 epoch 的实际读回被释放；旧 owner 仍存活并能计算，但其旧授权结果与写入被拒绝。 |
| 撤销 | 3 | replica-a | 0 | 已排队的 epoch-2 结果被拒绝；两个活进程观察撤销后另发新请求，仍被拒绝。 |

两个 run 都有三个不同的 `boot_id_sha256`、三个不同的 `instance_sha256`。但 **`machine_id_sha256` 的不同值数量为 1**：三个 runner 共享镜像中的 machine-id。独立性结论依赖不同 boot/instance 与 runner job 证据，不能把共享 machine-id 或自报身份当作不同物理宿主机的硬件证明。

同进程链条通过完整服务日志核验，而不只相信 final 的 `same_pid` 字段。每个进程从 ready 到 stopped 的 server 身份完全相同，请求 ID 不重复，sequence 连续递增；source 为 1–6，两个 replicas 各为 1–7。prepare 的 response、activation 后的 normal/pending response、撤销后 acquire、最终 status 和 stop 均与对应日志逐对象一致。公开完成回执中的日志与 diagnostics 副本字节相同。

## 4．撤销请求、拒绝与 durable authority 的独立核验

每个 run 的 final 含以下 10 项检查，全部为真实拒绝并报告通过：

- 迁移前只读 replica 不能写。
- 活着的旧 owner 在迁移后不能释放旧读结果。
- 旧 owner 的旧 epoch 写入被拒绝。
- 旧 owner 即使自称当前 epoch 也不能写。
- replica-b 在迁移后仍为只读。
- 活着的旧 owner 在撤销后不能释放结果。
- replica-a 的已排队结果在撤销后被拒绝。
- replica-b 的已排队结果在撤销后被拒绝。
- replica-a 观察撤销后发出的新请求被拒绝。
- replica-b 观察撤销后发出的新请求被拒绝。

对于最后两项，核验器逐一匹配 `request_id`、node、checkpoint、run binding、`seen_epoch=3` 和实际 revoked message 的 SHA；final denial 必须对应同一请求。completed 回执再绑定实际 final SHA，并以同一进程的 status/stop 结束。因此既检查了撤销前已计算但未释放的结果，也检查了撤销后实际重新提交的请求。

每份 final SQLite 都以只读方式独立打开，重新计算 **18 个事件**的 canonical body、parent hash 和 digest，重放状态及 grants 投影，再与实际 SQL tables 和导出的 events.json 对比。状态严格为 **epoch 1→2→3**，最终 `owner=replica-a, valid=0`；10 个 grants 中 5 个已消费。数据库文件的实际 SHA 与 final anchor 一致，检查前后文件未变化。

这条 live 路径验证活进程的隔离与撤销，没有在三个 VM 上杀死宿主机，也没有对 live controller 进行 SIGKILL。两个 controller-process SIGKILL 是另一个七 VM 串行实验的内容，不能把其尚未完整收尾的结果混进 live run。

## 5．字节与时间口径

| 层次 | 首轮 41157593644 | 加强校验版 41157871480 |
|---|---:|---:|
| 15 个 GitHub 原样 ZIP 合计 | 171,360 B | 171,408 B |
| 原始 artifact 展开内容 | 701,599 B | 701,557 B |
| 本地完整证据，含 ZIP、展开、元数据、源码和审计 | 1,033,043 B | 1,033,670 B |
| 无损 xz 传输 part | 253,704 B | 255,840 B |
| Part + manifest | 269,273 B | 271,409 B |
| 各协议 phase 的 wall 求和 | 51.321898 s | 697.196067 s |

Phase wall 包含 artifact 等待、下载和并发重叠，不能将求和解释为端到端延迟、CPU 总量或模型计算耗时。较新 run 的 replicas 在等待 source 获得 runner 时已有长时间 artifact 等待。没有独立测量完整 CPU、部署 RSS 或同条件网络延迟；不能据此宣称跨节点性能优势。

完整证据有 deliberate 复制：原样 ZIP 与展开内容同时保留，diagnostics 与完成回执保留服务日志，源码与独立审计也单列。xz 只是证据传输压缩，不是 learned memory 的内容压缩收益。

## 6．七 VM 串行实验的 checkpoint 状态

Run `41157593645@024acd29` 的 source、replica-a、replica-b、controller 四个 jobs 已成功。controller 的实际步骤为 “Commit migration, kill before acknowledgment, restore and fence old owner”。随后两个 readback jobs `124417049698`、`124417049703` 排队；此 checkpoint 尚无完整 final 收据。

因此当前不能宣称该 run 已独立核验七个不同 boots、两个 SIGKILL、两个冷读回和最终撤销全链。后续要收齐同 run/attempt 的 source、两个 replicas、migrate、两个 readbacks、final，独立核对七个身份、SIGKILL -9、epoch 1→2→3、旧 snapshot 拒绝和撤销结果。失败也须保留，不能换用其他 run 的成功 stage 补齐。

上述“前四 jobs 成功”是 GitHub job 进度，不能代替本地完整 artifact 审计。两个已完成 live 包可以独立发布，不依赖此排队实验。

## 7．边界与复核入口

已经验证的是受信任 GitHub workflow/run 中、通过 artifact relay 交换消息的研究协议。它的 release authority 是单一 Python/SQLite controller；逻辑 owner 的变化不等于形成分布式共识，也不等于原生 Rust owner authority 已接入这一跨机器路径。

当前结果未覆盖：物理宿主机故障或硬件证明、网络分区可用性、分布式共识、恶意管理员回滚、optimizer 迁移与异地续训、参数机器遗忘、开放记忆质量改善或 production activation。检查点与旧参数仍可保留，撤销控制的是授权释放，不是证明所有历史权重已物理消失。

归档恢复命令从仓库根执行，输出目录必须不存在：

```bash
python3 qualification/memory-cell-v12/evidence_pack.py restore \
  --pack qualification/memory-cell-v12/evidence-packs/federation-live-41157871480 \
  --out qualification/memory-cell-v12/evidence/federation-live/run-41157871480
```

恢复后，`GITHUB_ARTIFACTS.json`、`GITHUB_JOBS.json`、`SOURCE_SNAPSHOT.json`、`ARCHIVE_VERIFICATION.json`、`INDEPENDENT_AUDIT.json` 给出各自的身份与结果。`POST_RUN_TOOLS/hepta_federation_audit.py` 是不导入 producer 的独立核验器；对恢复出的该 run 目录重跑即可复核原 bytes。将两个路径中的 run ID 改为 `41157593644` 可恢复首轮。不要使用当前分支的新源码替换归档中的实际执行源码来解释较早运行。
