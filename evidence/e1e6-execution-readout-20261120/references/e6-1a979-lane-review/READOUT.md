# NoUpdate13：启动 continuation 与 Restore 竞争同一个 Historical client

## 真实首因与证据范围

精确源为 `1a9799686243c2be0ee393ba364e091029cfb944`，tree `931a344b1ea3e2ddf45e917ea4b3ae37c504ed05`。本层 20 份源码逐字匹配该源实际 inventory。原 pipeline 的 18 framing、47 原组件、两项 Root 组件和 Root 机制通过；完整普通 NoUpdate 父仍失败。父 JUnit case 为 65.898 秒，suite 为 65.905 秒，不能把 wrapper 含准备的时长混为父测量。

原父报告最终 `successor is closed`。同一 JUnit 保留的 B daemon stderr 给出更早的明确链：**一个 Historical RPC 正在执行，Restore 的前观察竞争同一个私有 lane，后者失败并永久 fence client，前者在返回后也因此失败。** 尚未到 Evaluation、真实新 C 或新增同步 drain；此次不能评价 C-drain 修复成败。

本层原件是完整 JUnit 与实际 pipeline / wrapper JSON。`DERIVED_B_DAEMON_STDERR.txt` 是从 XML 的 system-err 解码并截取的派生文本，不冒充尚待回收的原 child stderr 文件。无宿主读取、源码修改、Rust observer、测试、模型、训练或验签执行。

## 可核的实际顺序

| 原日志 | 精确上层归属 | 含义 |
|---|---|---|
| request 28、29 | runtime `attach_sources` → delivery `require_original_source` | 启动前原 source 检查完成 |
| `historical_source.rs:389`；request 30、31 | `run_delivery` 的原 claim 操作 | 真实原 journal claim 受同一 Prepared 操作前后观察；之后才可 Submit |
| `historical.trace.stage work=restore` | `run_original_historical_stage(Restore)` 在启动 blocking work 之前打印 | 表示 Restore 已被调度，不等于它已取得 Historical lane |
| `dataset_historical_ledger.rs:155`；request 32 | continuation 启动的 `require_current_historical_source` | 这条直接 source 检查没有取 Q24 aggregate semaphore |
| `historical_stage.rs:63` 的 Prepared / receipt 标签，随后 `historical_client.lane_busy` | Restore blocking work 的实际前观察 | 它已取本 aggregate permit，仍与直接 source 路径在同一个 Historical client 上相撞 |
| `observe_before_action` → operation fence → `stage.final_result OwnerUnavailable` | Restore 失败 | 没有绕过、重试或按成功解释 busy |
| `historical_client.fenced_after_exchange` → continuation original error | 原 request 32 持有者返回 | 共享 client 已由竞争者 fence，故即使原交换返回也不允许继续 |
| delivery Pending / joined error、successor closed | 原联动取消与关闭 | 是后继失败，不是首因 |

`lane_busy` 的实现使用 `try_lock().inspect_err`，单看该标签本身也可能涵盖 poison；本次额外同时存在 request32 已进入交换、随后它的 `fenced_after_exchange`，且 Restore 的调用标签和错误紧接其间。结合确切控制流，可定位这一实际竞争，而非仅凭泛化的 `Unavailable` 猜测。

## 同一个真实 client 的连接

`production_post_a_q24` 把同一 `Arc<OriginalHistoricalTaskReadReceiptV1>` 和同一 Prepared 放入 `RegisteredHistoricalLearningSourceV1`，并把它同时交给原 delivery 与 continuation。Prepared 的历史检查要求 batch ledger 所持 receipt 的 `Arc::ptr_eq`，不是两个同内容但独立 client。

`OriginalHistoricalLearningDeliveryV1::run` 对 delivery 与 continuation 使用原 `tokio::join!`。delivery 在 readiness 循环后 claim、Submit；runtime 收到 Submit 后调度 Restore。continuation 也有独立 readiness 循环，随后同步调用 `require_current_historical_source`，再等待 Decision。两路 readiness 并不定义先后：NoUpdate12 恰好 continuation 先完成，NoUpdate13 则 claim / Submit 先行。

Restore 的 `try_acquire_owned` 只串行化 Q24 aggregate owner；continuation 这条原 direct source check 不走该 semaphore。因此不能用 aggregate 已串行这一事实否定 Historical transport 的真实竞争。`RootHistoricalTaskReadClientV1::exchange` 的原 `try_lock`、fence、原 scope / session / frame / deadline / sequence 检查均应保持。

错误中的 `original training material` 是 Prepared / Dataset 的错误包装，不足以证明已调用 `production_post_a_c_task::actual_model`；本次确切位置是 Decision 等待之前的启动 source 检查。尚无 B Evaluation 或 C completion 资格。

## Root 选择的最小两阶段修复约束，尚未执行

在启动 delivery 的 claim / Submit 之前，先消耗**同一个 continuation owner** 完成它原有的 readiness、admission、完整 source physical before / after、trust 检查。成功后才进入旧 joined delivery 与已准备 continuation 的 Decision 等待。

准备类型应有私有字段，并直接持有原 continuation、同一个 `Arc<AgentdState>` 与同一 child cancellation token；其后 run 不接收可替换的 state / token。不返回 Root read、activation、授权快照或可转用凭据。该阶段只固定本来并行的启动顺序，不将一次观察当成后续 effect 的持续授权。所有 Decision 后的实际 Source / Current / trust / material / custody / expiry 守门原样保留。

| 结果 | 必须保留的行为 |
|---|---|
| readiness 前取消 | 显式取消分支，不构造 Prepared；同一 owner 退出，旧 shutdown / close 生效 |
| source 或 trust preflight 失败 | 返回确切原错误；没有新的 claim / Submit；不重试、不另造 Root client |
| 既有 Pending / Completed journal | 原件不修改，不因 preflight 失败清空或改选 Create；恢复仍只能原 readback |
| fresh preflight 失败 | 原 assembly 已初始化的 journal header 可以仍存在；不人为制造 Pending 以伪装执行过 claim |
| preflight 成功后取消 | 原 token 与 end 仍有效，旧 join / first_failure / close-and-await 行为保持 |
| delivery 已实际 claim 后失败 | 保留真实 Pending 与同一 journal / witness；未知结果不得 redispatch |
| 后续 Source 改变 | 后续原 stage / publication 检查仍重新读取实际 Root，不复用 preflight 作为授权 |

本次原 NoUpdate13 日志已越过 claim 并进入 Restore，对应旧代码的失败分支保留 Pending；这是一项控制流结论，尚不冒称此层已离线解码 journal / witness 原字节。后续实际原件可以独立补证。

该修复预期**不减少帧数、不增加 64、不加 timeout、不把 busy 变可重试**。Adopt 74 的独立成本障碍仍存在。候选代码由 hia 单独拥有，本层只给约束与来源，不改其文件，不产生通过资格。

## 引用

- [完整成员与 SHA](MANIFEST.json)
- [精确源码 pins](SOURCE_PINS.json)
- [实际 pipeline](originals/PIPELINE_RESULT.json)
- [实际 wrapper](originals/WRAPPER_RESULT.json)
- [原 JUnit](originals/ordinary-post-a-no-update.xml)
- [派生 B stderr](DERIVED_B_DAEMON_STDERR.txt)

源码永久链接前缀：`https://github.com/TrillionniumFoundation/hepta-private-ci/blob/1a9799686243c2be0ee393ba364e091029cfb944/codex-rs/hepta-agentd/src/`。
