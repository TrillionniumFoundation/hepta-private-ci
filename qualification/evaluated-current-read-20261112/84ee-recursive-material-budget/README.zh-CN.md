# 原始读取的递归预算：固定 84ee9c2

> **静态条件路径审计；没有执行产品测试、构建或 actor。研究状态 HOLD，owner_decision = null。**

固定源码：`84ee9c2ed0db8b20b792634d775f9b4f97a34578`；树 `6f1d7265ef1a58a0de1cc8da75ce142111743d85`。运行时生产字节与已审 `ff564227a417febe21a8187e650d5d80223dff42` 相同。本报告不是对后续移动分支的判断。

## 1. 可证明的缺口与适用条件

这条完整的原始 Version/S/C 成功路径保留同一个 `shared_evaluated.evaluator` Arc。它需要 **Q = 70 + 10R 次 B Readback**。若该真实 evaluator 由新的 **Bound B** 宿主服务，B 的 primary/retention 原成员共享同一个实际 Trainer 只读连接；一次完成的 B Readback 对该连接执行三次真实读取。因此：

```text
只需 Version/S/C 同一 B Arc：
B→Trainer 的条件成功请求需求 = 3Q = 210 + 30R > 128
```

这里的 128 是原 Trainer 只读客户端和服务端都执行的生产上限，不是从 toy fixture 推出的约束。超过上限表示该条件成功路径无法靠这些原连接完成；它不表示已有 210 次请求成功执行。

| R | Version/S/C 的同一 B 连接需求 Q | 该 Bound B 的同一 Trainer 连接需求 |
|---:|---:|---:|
| 0 | 70 | 210 |
| 1 | 80 | 240 |

若另外确认 Root 的 B 命令和 Version 的 B 命令确实到达**同一个** Bound B 宿主，才可以加上 Root 的 `b = 11 + 2R`。一次 B Execute 比 Readback 多一次 Trainer 检查：

```text
额外合流条件下：3(b + Q) + 1 = 244 + 36R
R = 0：244；R = 1：280
```

同一个 receipt、cut、actor ID 或签名不能证明两个连接由同一宿主服务。主结论采用不需要 Root/B 合流的 `210 + 30R`；`244 + 36R` 是附加拓扑条件下的总需求。

## 2. 单位、边界与证据

- **R**：完成强制六 cut checkpoint 后，再进行的完整六 cut Root readback 次数。R = 0 表示协调器内部完成；R = 1 包含一次完整结果取回。R 不是重试、seed 或轮询次数。
- **P**：实际原 Candidate artifact 字节数除以 2048 向上取整，已准入的原限制为 1 至 17 页。
- **m**：B panel 的实际 primary 与 retention 成员总数，至少为 2。
- **一对 T/B 读取**：两个不同原 purpose 连接各一次真实请求，不能把它记为一个总 frame。
- 路径包含一次原 fresh Version publication、原 issuer/FinalUse、一次实际 C runtime config 消费、S/C owner factory 和 readiness 初始化；不含重试、失败调用、额外诊断或额外授权观察者。
- 不同物理连接分别计数。只有源码持有同一个 Arc 或实际装配已证实时才合并。
- 这里没有全系统通用上界；额外原准备、真实训练/评估工作及其他授权调用仍会增加需求或更早失败。

完整机器可读图与每条计算见 [AUDIT.json](AUDIT.json)。[SOURCE_PINS.json](SOURCE_PINS.json) 列出 105 个源文件的精确 Git blob、SHA-256 和字节数：24 个本轮全文重取并独立计算；81 个与先前已逐字验证的 immutable 原件相同，且均与本轮实际发布树的叶逐一匹配。两个集合的验证方式在清单中明确区分。独立审阅者另封了 43 个原源 pin 的审计，见 AUDIT 中的 `independent_review`。

## 3. Root 的强制检查，不重复叠加旧公式

实际 resident 在每一阶段 Execute 后取得真实 `original_attestations`，验证原角色与签名，再调用 `gate.checkpoint`。evaluated route 返回本次完整向量，不会再走 legacy 的逐 receipt 读取循环。250 毫秒 watchdog 是本地 Root registry/store/current 检查，不额外产生 T/B/Material RPC。

| 实际阶段 | Evaluation facade 次数 |
|---|---:|
| B Execute | 1 |
| 强制四 cut checkpoint | 1 |
| S Execute 前后 | 2 |
| 强制五 cut checkpoint | 2 |
| C Execute：开始、Ready 后刷新、结束 | 3 |
| 强制六 cut checkpoint | 2 |
| 每一次额外完整 Root readback | 2 |

故 `b = 11 + 2R`。每次 Evaluation facade 产生 1 次真实 B 命令、2 次 Candidate client 读取、6 次共同 E/D/T prefix 读取。六次来自 Candidate 前后各两个 prefix，加上 B 前后各一个。随后 `evaluated_predecessors` 使用同次实际末尾 D/T/B 观察，不额外读取。

Candidate 的第一次 client read 传输 P 页，后续每次只执行一个原 Current frame，因此 Candidate 连接总量是 `2b + P − 1`，不能把每次读取都乘 P。

原 fresh E/D/T 初始阶段的 Root 端点分别为 9/7/3 次；其中 T 是 1 Execute 加 2 completed Readback。加入 evaluated 阶段后：

| 原物理连接 | 本路径条件需求 |
|---|---:|
| Root E command | 75 + 12R |
| Root D command | 73 + 12R |
| Root T command | 69 + 12R |
| 其中 Root T completed Readback | 68 + 12R |
| Root Candidate | 21 + 4R + P |

这些是各自独立连接的计数，不等于下层 Material evidence 连接的计数。

## 4. Version、S、C 的完整 Q 表

一次实际 `read_original` 在真实 publication/artifact 读取的前后各执行一次 `require_cut_current`，因此读取 D/T/B 各两次。第一次 bind 读取 D/T/B 各一次；已绑定的 evaluated context 只校验固定 cut，不再算一遍 live read。

| 原 Version 操作 | T/B 对数 |
|---|---:|
| 初始 bind | 1 |
| Prepare：cut 1 + 原 publication prepare 2 + 最后 read_original 2 | 5 |
| 原 issuer claim 与请求前的两个 read_original | 4 |
| FinalUse publish：外层前 2 + 原 publish 2 + 外层后 2 | 6 |
| run_original_c 消费原 config 前 | 2 |
| 实际 S owner factory 前后 | 4 |
| 实际 C owner factory：前后 4 + 一次 S Evidence 2 | 6 |
| 实际 readiness factory 前后 | 4 |
| 四次必需的完整 Version 读取，另加 R 次 | 8 + 2R |
| **Q_V** | **40 + 2R** |

四次必需的完整 Version 读取分别是 Prepare/Progress 后第一次完整 publication、S checkpoint、C execute、C checkpoint。Progress 是调度状态，NotReady 是 readiness 状态；它们各增加自身连接 frame，不会每轮重新做 T/B 查询。原 lifetime 与 sleep 约束仍可能更早终止。

| 原 S/C 操作 | 请求数 | 每次 T/B 对数 | 合计 |
|---|---:|---:|---:|
| Root 的实际 S command | 6 + R | 2 | 12 + 2R |
| Root 的实际 C command | 3 + R | 6 | 18 + 6R |
| **Q_SC** | | | **30 + 8R** |
| **Q = Q_V + Q_SC** | | | **70 + 10R** |

一次 C command 的六对来自直接 T/B 前后两对，以及两次实际 S Evidence 各两对。C factory 的一次 S Evidence 已在上一表的 6 中，不能重复增加。Version 的 D command 另为 `34 + 2R`；原 publication prepare/publish 的 context 检查不读取 D，不能直接让 D = Q。

## 5. 新 Bound B proof 实际减少了什么

新增 B training proof 借用在一次原 Host 调用内。它绑定原 Trainer Arc、完整原 Training receipt/签名、scope/principal/trust，以及本次私有调用身份。8m 个成员逻辑 slot 中，仅首尾实际读取 Trainer，中间 slot 验证相同 immutable 原 pin；错 Arc、错 context、错顺序、部分完成或取消后的复用仍拒绝。每个原成员的 cohort、Cell、Qualification、execution 与 Source 检查均保留。

| B 内部工作 | Readback 实际 Trainer 读取 | Execute 实际 Trainer 读取 |
|---|---:|---:|
| Host panel 首尾 proof | 2 | 2 |
| 原 receipt owner | 1 | 2 |
| **同一 B→Trainer 连接总量** | **3** | **4** |

旧 e72 的 `8m + 1` 不能继续用于新 Bound B。默认 Individual 模式则仍需分别看连接：primary 每次 B call 为 9 次、每个 retention 为 8 次；一次 Execute 对 primary 多一次。不同 primary/retention peers 不能相加成同一个 128 计数器。

默认 PublicationFixture 的 B 仍使用独立的 primary/retention fixture evidence peers；它的外部 T 即便使用真实 SourceBound Stage，也不能证明 B 使用同一个真实 Trainer。新 TrainingFixture 与 `into_host_from_original_training_readback` 才明确构造 Bound 模式。读取这些测试源码只证明接口和预期，不代表测试执行成功。

## 6. 继续向下展开到 Material

新的 Trainer/Candidate 单调用 read-set 已把一次成功读取压到 Source 前后各一次。每次 Source capture 对原 E、D、remote Source 连接各读一次，因此一次 completed Trainer read 或 Candidate Page/Current 对各物理 Material 端点的贡献是 **2**。

只有 Root T、Version T、Bound B readonly T、Candidate 确实借用同一个 SourceBound Stage 和同一组 held Material 端点时，才能合并以下各项：

| 汇入同一 Stage 的原操作 | Trainer/Candidate 次数 |
|---|---:|
| evaluated 阶段 Root T | 6b |
| Version/S/C T | Q |
| Root/Version 同 B 宿主的 B readonly T，含一次 Execute | 3(b + Q) + 1 |
| Candidate P 页与后续 Current | 2b + P − 1 |

每一个共同 Material E/D/remote Source 端点的 **post-training readonly 核心需求** 为：

```text
2[6b + Q + 3(b + Q) + 1 + (2b + P − 1)]
= 22b + 8Q + 2P
= 802 + 124R + 2P
```

| 条件 | P = 1 | P = 17 |
|---|---:|---:|
| R = 0 | 804 | 836 |
| R = 1 | 928 | 960 |

早期 Root 的两个 completed T readbacks 另贡献每端点 4 次。另已逐源展开 fresh bootstrap 的 18 次和真正 missing Trainer fit 的 10 次，详见 AUDIT；其他 B/panel/retention 原准备工作不在这个核心内。因此这不是全系统上界。

**生产 Material legacy evidence/source 服务使用 checked u64 循环，不是 128 次上限。** 每次 exchange 的原 500ms 与绝对 300s lifetime 仍适用。有限 fixture 的同一物理 Material peer 才有 128 次计数上限。local Source profile 没有 remote Source frame，E/D 与实际本地 Source 校验仍存在。请求次数不能直接转换为实际时间或证明超时。

## 7. CURRENT transaction 与网络预算分开

最终组合源码的 scoped CURRENT transaction 是 Selection 6 个逻辑 slot、NextUse 9 个逻辑 slot。首尾实际读取 CURRENT，purpose 在 slot 1 校验，位于首次实际 CURRENT 与 Source 输入之后、任何 native read 之前。实际 Source/Cell 末尾校验和完整签名保留。公开 individual wrapper 仍逐 slot 真读。

该优化减少本地 CURRENT 的重复读取；它不会自动减少上面计算的原 T/B 网络请求。不能把这一局部去重计为全链 128 缺口已经闭合。

## 8. 下一步候选切点与不可省略的证明

目前只给设计，未改运行时代码、cap、deadline 或协议。

1. **Bound B Readback 的中间 Trainer 读取。** 可研究让原 completed receipt 校验消费本次已有首尾 Trainer proof，保持完整签名/角色/时钟校验；Execute 的原 preclaim live read 仍保留。即使 Readback 从 3 降到 2，Version 单支仍为 `2Q = 140 + 20R > 128`；Root 同宿主时为 `164 + 24R`。单独实施不足以闭合。
2. **Version 同一次 factory 的嵌套 cut。** 可逐个研究一个私有、借用、不可逃逸的完整 before/after cut 是否能供内层只读校验复用。必须保留每个实际 Artifact/CURRENT/Source 检查；真实 effect 之后不能复用 effect 之前的 proof，也不能跨请求缓存。
3. **C 读取 S 所带来的共同前驱递归。** 需在真实 owner/协议边界内给出完整同调用 read-set。不能把普通 Evidence 当跨宿主借用 token 或 Fresh 权能，不能在持有 Trainer lane 的情况下回调该 lane 引入重入或死锁。

任何候选都需要重新给出按原连接划分的完整预算、首尾撤回反例、错身份/顺序/签名反例、取消和部分完成后的拒绝，以及原完整 source/native 门的实际结果。局部节省不能代替全链闭合。

## 9. 与已经观察到的失败保持区分

原 timeout 也按 purpose 区分：S/Material evidence 的上限是 500ms；原 owner command channel 单独允许最多 30s 的请求 timeout，且同样最多 300s lifetime。具体调用者原传入的 timeout 保持不变，不能把所有命令 frame 都写成 500ms。

旧 evaluated S 第一次调用的 callback 约 600ms，返回 `PredecessorUnavailable`。它的真实 inner Panel/Qualification 错误仍应由对应原诊断解释；本报告不把新的 resident/Bound B 条件计数套到默认 PublicationFixture 上。首字节到达前的 idle 可使用绝对 lifetime，因此 exchange 等待总时间也不能直接当作 500ms callback 的预算。

历史 e72 审计、暂停的五文件 read-set 草稿及旧 106/32/616 数字保留原件；它们未被本次报告采用为已运行结果，也没有叠加进新公式。这里始终是工程静态审计，研究结局 **HOLD**，`owner_decision = null`。
