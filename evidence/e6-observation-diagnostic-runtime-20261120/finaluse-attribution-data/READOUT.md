# NoUpdate12 的两个 FinalUse claim：仅保留 DATA 的归属补充

**两个 40 B claim 可以分别归属到 A 初始化和 A→C 的原模型继续使用发布。** 归属依据是已封存 grant / intent / witness / publication 的完整字段交叉，不是由两个 claim 的数量猜测。这没有授予完整 FinalUse、cold D、Adopt 或整父通过；原 dbd6 NoUpdate12 仍在 C Generation 的 `is_drained=false` 处失败。

实际源码身份仍为 `dbd6a00992b60f4b33e8f10c2defda031d123bcb`。已封存的 Training/B/ACK 68 件清单 `d21f91f9668243dbed3e367dd69cc3b1e0cefe6486f576bac41ce324f58c3bd4` 未改，本补充是独立层。

## 两条记录如何对应

| 位置 | 完整 nonce | 保留 grant | destination 与完整 intent |
| --- | --- | --- | --- |
| device `authority.claims` offset 0，epoch 1 | `c40fc13a246653135f1ca2b252049bce437e3be42438aa45a8cae603b31b5ab1` | `ordinary-original-root:1:2` | `agentd.cell-generation.initialize`；operation `ordinary-original-a-initial`；target run 为 `ordinary-original-a` |
| device `authority.claims` offset 40，epoch 1 | `c2a82d055b9f477a212907ccd61a13bb23b876a10bb49cb9b16a43e2a1150053` | `ordinary-original-root:1:4` | `agentd.cell-generation.next-task-same-model`；完整 intent 的 previous 为 A，target 为 `ordinary-original-c` |

两条 claim 合计 80 B；notes claim 是零字节。精确 `final_use_store.rs` 规定每帧为 8 B 大端 authority epoch 加 32 B nonce，`append_claim` 将其写入并同步。claim 帧本身没有任务 ID；任务归属来自下列额外材料。

- A 的 retained `initial-run-start` frontier 为 finalized，其 original target、observed current 和 initial intent target 三者完全相同；initial signed grant 的 epoch/nonce 与第一帧一致。
- C 的 prepared publication grant 状态为 issued；它的完整 signed grant 与 current published record 一致，完整 intent 也相同。
- C 的 retained accepted publication 包含的 current 与独立 current frontier 相同；其中 previous target 与 A 的完整 target 相同，新的 target run 为 C。
- 两个 grant 的 signer、grant ID、epoch 与各自 dispatch-entry witness 和 device authority head 对应。C accepted revocations 与捕获的 device head 字段相同。

完整比较、原 request/scope/payload digest 字段及各项时点记录见 [ATTRIBUTION_READOUT.json](ATTRIBUTION_READOUT.json)，执行结果见 [RESULT.json](RESULT.json)。八份实际归属材料均保留精确原字节，路径/长度/SHA 映射在 readout 中。源码字节绑定及检查范围见 [SOURCE_PIN.json](SOURCE_PIN.json)。

## 证明边界

这是对封存 DATA 的字段一致性检查，不重新验证签名、活体 current/trust/revocation、权限或任何 Rust observer。签名和 binding digest 字段相互比较，未声称本补充重新执行了 signing/domain 算法。

两条记录是 nonce 的持久消耗，单独不能证明外部 effect 完成。第二条原 intent 的 `owner_drained_same_model` 描述 A→C 转移中的原 owner 条件，不能据此反称后来 C 自身已经 drain；原父随后观察 C 缺少 Drain 的失败仍然成立。三份 C frontier 中的保留 publication 字段提供发布记录的一致性，但也不是本次新做活体验证。

从这两条 claim **没有 D、冷恢复、退休后完整 acceptance 或最终结算的通过证据**。本补充只收窄过去“A/C 归属待核”的状态，保持整父 FAIL 与全部未获资格项。

## 读取范围与保存

先在已经恢复、逐 SHA 绑定的 652 份非 key 材料 / 8,576,320 B 中做有限 byte-pattern 查找，再对八份命中与 authority metadata 作字段比较。没有打开原 SQLite，也没有创建或打开分析数据库副本；DB/WAL/SHM 均未由数据库接口读取。没有读取私钥，新增 host、native、模型、optimizer、签名验证或 Git 操作为零。

[DISCOVERY.json](DISCOVERY.json) 保留查找结果；[CONSUMED_INPUTS_1.json](CONSUMED_INPUTS_1.json) 保留有限集合；[read_claim_attribution.py](read_claim_attribution.py) 为实际离线解析器。原物证、旧 68 件清单及正式报告均未改动。
