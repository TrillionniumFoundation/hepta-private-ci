# HIA / Cell 共同候选：语义学习、恢复与证据绑定

## 当前结论

本轮工程候选已提交到 [Draft PR #6613](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/6613)，精确源码为 `0c2b0c529882a0caeae23f8060a14e69475f4a14`。[专用 CI 44230303266](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/44230303266) 完整通过。下载后的独立审计通过，616 个原件、60,961,041 字节在审计前后保持不变；两个维护 lane 的 runtime stdout、磁盘原件与独立 review 再次对应通过。

**这证明受控环境中的共同候选、真实调用与实验/恢复流程成立；学习收益、长期可塑性、完整成本优势和 effectful 在途迁移仍未完成。** 本轮没有合并、普通 daemon 采用或生产激活。

本目录是证据提交，父版本是上述被测源码。证据提交不会替代被测源码 HEAD，也不会把其他版本的成功记录转移给当前候选。机器状态见 [FINAL_STATUS.json](FINAL_STATUS.json)，详细原件审计见 [FINAL_AUDIT.json](FINAL_AUDIT.json)。

## 1. 固定候选与执行来源

| 对象 | 本轮精确身份 |
|---|---|
| Cell / 实验源码 | `0c2b0c529882a0caeae23f8060a14e69475f4a14` |
| Hepta / HIA checkout | `8ba46fc7a112fc220cdcbbd48dc5d24fda76a738` |
| HIA compiler pin | `f33d8da316de8fdf27b504371f1a5310997ff548` |
| runtime | `73b5c33d5762eefc0554a86750094350f18ae6a0` |
| 实际运行候选 SHA256 | `36116708f9ce77685a8f2c488a4d642050f1fc14acf71cd769037404aeb41697` |
| HIA native image SHA256 | `c475a22313d401e84d5e0b13c935aabb4615c6da15aba3e6083f842d35f54812` |
| runtime binary SHA256 | `8a00d4d6edf6ce5a7c374eccf16605d1e18a043d9fa990215bbc736861de6130` |
| runtime config SHA256 | `828986fd469f1e86553fe57fc213c806fd31b9675e55236c6de66ab64b064c55` |

候选的 262 个条目覆盖 64 个 Cell 来源文件、193 个 HIA 来源文件和 5 个数据/模型/构建原件。每个来源保留真实 HEAD、tree、Git blob、SHA256、长度和执行位；设备、Python/NumPy 二进制、线程设置、模型和输入摘要在原始 candidate 中。维护实验中派生的父模型、训练候选、选中版本与数据另有各自 manifest 和原件摘要，并和真实运行输出绑定。

本地 HIA/GRU 控制的 origin candidate 为 `4305fda003831c5629fa495115697f7741e3c6785fcdf731e4e96d268027a4c5`。随后加入实际 runtime 二进制与配置身份产生上述运行候选。独立审计核对其源码、模型和来源身份清单未改变；两种 candidate 的验证范围分开保留。

默认冻结拒绝 dirty、缺失或未跟踪的必需执行源码；执行入口拒绝被裁剪的 semantic、updates、reviewer 与 package 源码清单。portable provenance 保留原冻结来源，不冒称搬运后的目标 checkout 已得到原 HEAD 的运行资格。

## 2. 已实现的执行与恢复约束

实际路径为原生 HIA continuation → 真实 MEM/PRED GRU → 明确 Cell owner → runtime 的固定执行入口 → 持久经验、状态与原始输出。本轮 runtime 环境是 CI 中显式启用的 disposable SSH/operator loopback fixture；普通 daemon 的 FinalUse/采用入口没有因此获得资格，子进程也不宣称具有 OS sandbox 隔离。

三项实际作业都绑定同一运行候选。每项首次会话只有一次 `process_start`；新控制器冷会话重新调用 `process_status` 与 `process_read`，不重新启动作业。审计从分页协议重新组装全部 stdout/stderr，并比较原字节、摘要、终态 nonce、job 和冷观察。

| Lane | 原始 job | 首次 start | 冷会话 start / status / read |
|---|---|---:|---:|
| 单次 Cell 调用 | `1a1ecb754e7-1edf-1` | 1 | 0 / 2 / 1 |
| 原 syntax campaign | `1a1ecb75e19-2096-1` | 1 | 0 / 2 / 16 |
| semantic campaign + 三类实例 | `1a1ecb78e71-28c7-1` | 1 | 0 / 2 / 18 |

桥保留第一次完整终态。重启后如 nonce、终态 proof 或输出字节变化，原证据仍在，观察降为 UNKNOWN；并发恢复通过 SQLite transaction 串行化；请求/profile 值复制避免调用方原地改写；丢失 start ACK 不自动重发；cancel 不等于完成。

语义 lane 的 RESULT、PLAN、OBSERVATION、updates RESULT/PLAN 在首次终态和冷读后都按固定路径重新核对原字节。独立只读 review 同时绑定同一个 RESULT/PLAN/native image；语义旧报告缺少新绑定记录时不能通过后处理升级为新资格。

## 3. 学习闭环的实际结果

语义任务使用固定输入/输出 oracle。编译通过后还须在真实子进程中执行并核对结果，错误输出、异常和超时均可见。A/B/C/D 的任务 ID 和确切源码不同，但仍共享合成缺陷族；这不构成独立真实来源分布。

A 产生经验后，两处各完成 16 次训练更新；B 独立评价；决定持久化后执行 C；冷进程恢复原状态并执行新的 D。评价复核重新检查 A-only 训练输入、模型动作、实际修复源码、子进程原输出及采用/拒绝记录。

| Cell | B frozen | B candidate | B deterministic | 决策 | C selected | 冷恢复精确 | 新 D-cold |
|---|---:|---:|---:|---|---:|---|---|
| MEM | 2/8 | 6/8 | 8/8 | NoUpdate | 2/8 | 是 | 失败 |
| PRED | 2/8 | 2/8 | 8/8 | NoUpdate | 2/8 | 是 | 通过 |

关闭学习和不保留经验的 B 组在两处也均为 2/8。该语义 campaign 共 733 次 native completed（MEM 269、PRED 464），208 次父阶段及 4 次冷阶段 compile 检查，65 个实际语义子进程。**2 次完整 NoUpdate，0 次 Adopt。** C 仍使用被选中的原模型，不能拿 C 结果主张采用后收益。

现有严格门要求超过所有基线，而 deterministic 已是 8/8；同一有限面板没有合格 Adopt 的空间。原门和强基线保留。丰富真实任务与能力表达之后应另行冻结研究协议，原面板继续作为回归哨兵。

## 4. 同一 runtime 中的三类实例

| 实例 | 实际观察 | 当前接受状态 |
|---|---|---|
| 代码优化 | 24 对任务输出与状态相等。loop 整 owner 调用合计 144.805 ms；builtin 141.816 ms，计入迁移试点为 142.767 ms | NoUpdate。单次观察有小幅 wall 优势，完整 build/能耗/并发进程树成本未知，不能主张完整成本下降 |
| 参数学习 | 直接核验同一 semantic campaign 的训练、B、决定、live 模型、C、cold 原件；没有再次训练来替换原结果 | 两处均 NoUpdate；尚无被采用的新能力 |
| 状态迁移 | 同 owner/partition 的空闲 GRU readout 升级，状态交接后新进程恢复并做新推理；迁移 1.689 ms，fresh-child 恢复/推理 125.628 ms | 限定范围通过；有 pending 的迁移被拒绝，原 pending 保留 |

updates 另有 52 次 completed 与 1 次故障注入后的 `cancel_requested`。这个 pending 是纯 Cell 控制，不是外部业务效果的丢失/重复统计。跨 owner、effectful 在途交接及拆分仍需独立协议与 receiver ledger 验收。

## 5. 成本口径

语义 campaign 的内部总 wall 为 4.783 s，记录 172 个窗口，其中 146 个为任务窗口。训练、验证、选择/切换、数据采集、共享 diagnostic、C/D 新诊断、cold process 与恢复均有明确阶段。源码编译、runtime 构建和实际 MCP/SSH 会话还有各自原件；整个 runtime qualification 的 32.749 s 含三项作业与冷控制器观察，不能误读为单次 Cell 延迟。

任务 p95/p99、样本数、缺失数和统计方法均已保留。多数 arm 只有 8 个任务，D-cold 每 Cell 只有一个；这些是观察分布，不是生产尾延迟保证。父/子与阶段窗口可能嵌套，不能求和；共享 A/B diagnostic 只计一次。

物理能耗、真实并发进程树峰值、队列峰值和完整系统成本保持未知。`ru_maxrss` 只按进程生命周期高水位解释。不能据此称完整成本已经可接受或自适应结构更有效。

## 6. 验证与保留的失败

当前同一次专用 CI 已通过：101 个生命周期/bridge/来源/语义/成本/绑定控制；21 个 native 测试方法及 175 个子测试；16 个本地真实 HIA/GRU 联合检查；3 个实际 runtime 作业及 3 次冷控制器回读；2 组只读 snapshot review 与最终原件绑定。下载后的独立审计和两个绑定 CLI 也通过，原件保持不变。

历史失败均保留：

| 来源 | 原始结果 | 后续处理 |
|---|---|---|
| `b2963dc` / CI `44227593782` | 旧 just 不支持仓库配置，尚未执行核心 runtime 验证 | 使用仓库锁定的 just 1.51.0 |
| `6dba4e8` / CI `44227913874` | formatter 改变源文件，源码未变 gate 正确失败 | 保存原 patch，核对 21 个 Python AST 未变，再提交精确格式结果 |
| `10939f7` / CI `44228252971` | runtime 执行通过；独立 reviewer 的固定 SHA 在格式化后过期，整 workflow 失败 | 原 ZIP/失败记录保留；外部只读复核单独记录；更新校验值并在最终 HEAD 完整重跑 |
| 反例控制 | 裁剪候选入口、替换终态字节、修改 callback 身份、替换内部一致结果集等旧实现错误接受 | RED 原件及修复后的行为控制保留在 supporting evidence |

专用流水线通过不代表整个仓库所有 CI 都已绿。通用 blocking CI 仍有 cargo-deny 及 Windows/macOS Bazel 测试失败。读取的失败目标涉及 exec-server、app-server、core、hepta-agentd 与 hepta-matrix-sdk；本轮没有修改这些 Rust 来源。基线 `f8e54c6` 也有对应门失败，但这不证明每个当前失败都具有同一个原因。没有据此合并或跳过必需门。具体观察快照见 [CI_STATUS.json](CI_STATUS.json)，已读取的失败测试与有限诊断见 [BROADER_CI_TRIAGE.json](BROADER_CI_TRIAGE.json)。

## 7. 真实维护任务与剩余研究门槛

[HISTORICAL_TASKS.md](HISTORICAL_TASKS.md) 和可执行 capsule 固定了 5 个真实历史维护任务：原 child 终态、nonce/witness、Qualification 回调身份、population 恢复身份、native image 身份。统一入口和第二次独立重放均观察到语义 RED/GREEN；28 个 Git blob 已核对。五任务来自四次修复、三个相依来源组，不是五个独立分布样本；gold patch 已读，不能作为当前助手未知的评价，也没有证明 Cell 生成了这些修复。

当前四动作/13 维表达不能直接修复这些真实仓库缺陷。下一版必须冻结共同诊断/候选补丁生成器与更丰富任务表达，让普通工具 agent、关闭学习、固定拓扑、无跨会话经验、成熟确定性及完整故障组拥有相同信息、容量和预算。

[EXPERIMENT_ACCEPTANCE.md](EXPERIMENT_ACCEPTANCE.md) 与 [OPEN_EXPERIMENTS.json](OPEN_EXPERIMENTS.json) 把十项未运行研究实验的阻断、来源拆分、预算、接受谓词与必需原件列清；未运行结果均为 null。共享/独立 head、GRU/其他核、有限拓扑变化、采用后的 C/D、多轮保留、完整成本与 effectful 迁移都继续保留独立门槛。

## 8. 恢复原始归档并复核

为遵守现有 500 KiB blob 上限，较大归档按不超过 480 KiB 分块。分块没有改变原 ZIP/tar.gz 字节。[ARCHIVES.json](ARCHIVES.json) 保存逐块及整包 SHA256，恢复入口已实际验证，结果在 [RESTORE_CHECK.json](RESTORE_CHECK.json)。

```sh
python3 restore_archives.py --output /tmp/hepta-evidence-new
```

输出目录必须不存在。最终 Actions ZIP 的 SHA256 为 `493dc472ae355991d7ba2161a94b6e4fafeb2340b4bd142c579645b0269c074a`。可解压到新目录后执行只读审计：

```sh
python3 -B audit_runtime_artifacts.py \
  --artifact-dir /tmp/hepta-final-extracted \
  --workflow-metadata FINAL_WORKFLOW.json \
  --output /tmp/hepta-independent-audit-new.json
```

历史任务包解压后，使用包内 `run_all.py --output <新目录>`。它需要 Linux x86_64、Python 和 NumPy；runtime 部分重放嵌入的 Python 生产脚本，witness 的 systemd 状态使用原受控 fixture，不能称为重新编译整个历史 Rust runtime。真实 child/effect、实际 native ELF 装载和真实 SQLite owner 行为均保留在原件中。

下载产物含 runtime 二进制与私有配置的绑定摘要；这两份原始字节未包含在可分享包中，独立审计明确标识不能重新散列它们。私有 SSH 密钥不在归档中。
