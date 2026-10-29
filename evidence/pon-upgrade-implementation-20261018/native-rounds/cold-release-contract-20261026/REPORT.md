# PN3 / I09–I10 完整冷加载只读审计（2026-10-26）

结论：**NO_GO / 完整冷 release 尚未闭合**。这些容量数字不构成一个已经证实的通用矛盾；它们属于不同 profile、角色与计量。已闭合的是一个使用预装 Python 运行时、从单机 loopback 获取固定十一项模型材料后，执行原签名加载/推理/拒绝推理/终态卸载的有限 I09 观察。完整运行时交付、I10 授权安装、普通下一任务与三轮收益均未闭合。本审计没有运行模型、构建、测试、安装、provider 探针、服务变更或新 campaign。

## 1. 五个数字分别约束什么

| 数值 | 原 profile / 角色 | 度量与边界 | 同一 owner 如何计费 |
|---|---|---|---|
| 922,881,591 B（约 923 decimal MB / 880 MiB） | ROG 已安装 CPU venv 的 RECORD 内容调查，29 distributions | 20,378 个存在的记录路径的文件长度之和；不是 wheel 压缩大小、完整解释器根、去重/物理占用、VM、RSS 或 FSIZE | 若作为新 release 的 installed tree 存于同一受控 host root，实际保留字节须进入该 owner 的聚合账。旧观察不构成这个新 admission |
| 432,269,632 B | 同一旧 venv 的 `torch/lib/libtorch_cpu.so` | 一个已安装共享库的文件长度；已经包含于 922,881,591 B，也包含于 44 个 native candidates 的 547,041,392 B | 不得再次加总成额外 432 MB。它没有自动成为 I09 的一个合法 base 角色 |
| 512 MiB = 536,870,912 B | 原 630 / setup3 每个 `trnm-cell` cache | logical quota 为 chunk bytes+每键32B 与 manifest wire+每键32B；另有独立 main-DB 文件/page image 的 512MiB 上限。两者不是两个可相加的配额 | 同 cache 必须同时满足 logical 与 mainDB 限制；WAL/SHM 不因此免费。每个 cache 独立受限，多个 cache 同时仍计入 host 总量 |
| 300 MiB = 314,572,800 B | `hepta-smollm-controlled-cell-release-v1` 固定十一材料中的八个 `base/*` 角色 | 每个 regular file 的未压缩长度及实际流哈希上限；另三个 adapter 文件各2MiB，sidecar64KiB | 不是整个 runtime/release、VM、RSS、AS 或所有任意文件的上限。不能把432MB共享库塞进不变的八角色，也不能为修绿放宽旧角色断言 |
| 2 GiB = 2,147,483,648 B | 原 `lan72h-630f871-20261025-setup3` 每个 data host 的受控 root | cooperative forecast/postchild `sum(stat().st_size)`；包括两个 slot 的 cache DB/WAL/SHM、输出、二进制、事件和 metadata。不是硬 quota、FSIZE、VM、RSS 或宿主空闲盘 | 保留 slot 与新的 cold candidate 重叠时同时计费；metadata64MiB在该总额内。原 profile 明确不做 model loading/complete runtime release |

详见 `cold-release-role-cap-local-independent-review-20261026-001/report.json`（本包 input-pins 精确绑定）。每个 role 的 cap 保留原值；本审计没有把不同 profile 拼成同一次失败，也没有提供新预算。

原 Pocket4 `provider-0133` 的 **UNKNOWN 1GiB 是 NETWORK response reservation**，不是磁盘占用实测。SSH255、目录缺失或当前可达均不能释放该 charge、推断原 native 终态或构造“2GiB 减 1GiB 磁盘”的伪冲突。原 setup3 总 FAIL / child UNKNOWN 不变，同管理员 LAN 不满足三独立管理员 / 故障域 WAN。

## 2. 哪些依赖与行为已经有真实证据

- 旧 runtime 调查读取 23,990 RECORD 行；18,731 个原声明 SHA 匹配，实际 size/digest mismatch 为0。但 3,612 个原未给 hash/size 的 pyc 缺失，原 `all_captured_targets_contract_pass=false` 保留。1,647 个存在但 RECORD 未给 digest 的项目（1,618pyc +29 RECORD自身）另测到41,867,102B；这些观测哈希不是原 wheel 哈希。原 wheel archives 没有留存，未绑定所有 unlisted files、解释器/stdlib、完整原生库图或原子 namespace。
- 53fb 的新 **CI unit** requirements 源文件固定31种 distribution（torch x64/ARM64两行替代项，共32条记录）与 allowed wheel SHA。它在 CPU CPython3.12 Linux 两架构的 unit scope 有价值；它增加 cryptography/cffi/pycparser，并非旧29distribution已安装环境的逐字快照。它没有提供轮子原字节/大小、解释器/stdlib、安装峰值、完整ABI或实际 cold release。不能从 requirements 声明继承一次新的模型/安装 PASS。
- **原 I09 run002**：Chain `4c8c2ee70d8aba1fc959900741e89335ddcd71f8` / tree `1cd27084a7fef9e4d6e4984a5780cf4c3951e72c`，Hepta `8d25c5d71f7401a383b4c80046c8b26811abe394` / tree `7d1aa7abb787610b03cd8a319a3f905f33acb2ea`。全新 SQLite3.51.3 caches 获取11对象 /269chunks /272,190,131payload B，消费者初始0chunks，含 cache-only materialize 与终态读回 **4.2576826509975945s < 原35s**。一个 loopback supplier，自然退出在 native 前。消费者与生产者 DB 各272,613,376B，这是两个实际文件，并非一个去重副本。
- 原 selected native case `real_cell_release_original_signed_load_query_and_terminal_unload`：1PASS /10.357s /0retry，131项为 selector exclusions。编译+命令131.049s不是10.357s case 时间。模型 generation3，真实 forward 67,453,520ns、48input tokens、原观察RSS1,149,550,592B。RSS不是磁盘或Whole-U/并发进程树峰值。3 authorizer bindings只产生2 durable nonces，第三个拒绝发生在 forward 前；原冷 journal 重开与原 wait4/reaped 卸载观察保留。
- 这一 controller **180.167288273s / exit1 FAIL**：`I10 selected installation UNAVAILABLE`。整个 native receipt仍UNVERIFIED，不得用有限 case PASS 覆盖它。无 CLI/Agentd E2E、CURRENT 安装、普通下一任务、三轮安装升级或收益资格。原97文件818,673,612B只在远端原目录保留。本次只读取原4份小型 manifest/result/freeze JSON与精确71a两份小源码；没有重新独立读取97原大件、权重、数据库或远端库字节。

完整依赖清单及31种CI依赖名称在 `dependency-inventory.json`，原安装29版本保留于该文件。

## 3. 真实 Cell loader 与权限路径

现有 `verify_controlled_cell_material_v1` 先验证固定11角色的TCM1/TCR1、SHA、实际流、family/source/profile/operation/参数等，返回私有字段的 `VerifiedCellMaterialV1`。它的 `start` 必须接收既有 control journal、ResourceGrant、FinalUse authorizer/runtime owner，继而调用原 neural read port。**字节校验不创建 selector/CURRENT、安装或执行密钥。** 原代码也明确 caller负责 private staging，这不是 held-namespace capability。

真实 worker 路径依次执行 material verification、现存 Python package imports、`AutoTokenizer/AutoModel.from_pretrained(local_files_only=True, trust_remote_code=False)`、真实 parent adapter load、Ready pin核对。八个base含269,060,552B BF16 safetensors，载入为原f32计算profile，不应把计算内存当文件配额。driver启动 `config.python` 指定的绝对路径；现 profile digest固定六个项目源码/family、actions及模型/contract digests、threads4，**没有绑定解释器、site-packages或系统动态库**。driver明确设置三个offline/GPU变量，原源不构成一个完整 hermetic import/runtime 根。运行时缺失应失败，不能借 ambient site/user/.pth/PYTHONPATH/库路径或在线下载冒完整 release。

Rust原consumer及worker会重验材料，但 HF 仍按路径重新打开；源码说明依赖受控private staging，而非整个 ancestor/material namespace跨检查到实际打开的held证明。下一步应在该已声明边界内补 admitted runtime/namespace，不能把一次hash校验当通用可变目录安全证明。

71a 的 selected-initial retained-owner API 源级保留原 authenticated CURRENT、不可续期 selector window、Unix FinalUse、journal、exact1model/1request/8GiB grant及120s启动/2s读取/250ms claim/1500ms I/O。它还没有普通Agentd生产调用者；与Cell download/I10安装没有自动拼接。request Completed 不等于 OS child退出；必须继续用原显式 shutdown/owner terminal/wait链。71a static fixture 的两字段修补不在本报告中升级为 actual compiler/native/model资格。

## 4. 在原 cap 内能否安排

**单cache不够存下整个922,881,591B安装表示**不证明流式获取不可能。若 runtime被版本化为多个可验证chunks/objects，受控materializer可以在验证、落到同一已admit目的namespace并建立实际持有责任后，按原cache eviction规则退休已消费缓存；不能在只得到一个hash或消费者仍可回读时提前退款。每个时刻仍同时计入当前缓存、DB/WAL/SHM、installed/staging、archive/extraction scratch、metadata、旧/新version、已unlink但仍held的对象和UNKNOWN。原 logical cache上限并不单独证明整盘峰值。

仅作不准入的算术：旧安装表示922,881,591 + I09十一材料272,190,131 =1,195,071,722B；再加一个全额512MiB的**文件表示假设**是1,731,942,634B，距2GiB仅415,541,014B。这不含完整解释器/stdlib/system libs、全部实际DB/WAL/SHM、旧version、archive/extraction/metadata/unknown，更不能同时又把512MiB当logical quota和physical file重复或漏计。旧runtime已经包含libtorch432MB与native547MB；勿再次相加。没有这些未知实测和峰值计划，不能宣称fit或不fit。

原 setup3 frozen forecast1,964,390,944B只余183,092,704B，连再加一份269,060,552B权重都超85,967,848B。这个既有 **NO_GO_FOR_ADDITIONAL_REAL_WEIGHT_PERSISTENT_RUN** 保留；它是冻结forecast，不是当前disk使用或既有run实际越限的证明。完整runtime不能借原campaign未分配的额度启动。原campaign roots是tmpfs；已有ext4 parent观察不证明硬quota、持久root或断电恢复。新的persistent namespace只有在原所有cap内完成同一owner持有/总账/恢复admission后才可使用；不能叫它“缓存外安装区”便免计费用，也不能删/重启UNKNOWN owner腾预算。本审计未创建该root、迁移文件或验证恢复。

所以：**有条件可行的工程方向是有界chunk消费+同owner全量目的根计费+有证据的退休/持久修复；在现有实测输入下，尚没有可以批准实际完整cold load的峰值预算和完整release对象。** 不需先换共识或增模块；沿既有PN3/I09–I10闭合。

## 5. 交给现作者的最小接口与顺序（建议，均NOT_RUN）

| 顺序 / 既有边界 | 最小可审接口 | 保留的条件及验收 |
|---|---|---|
| 1 / I09 release声明 | 在现有release/profile的显式版本下加入 `runtime_root` 身份：实际platform/ABI/marker/extras；解释器+stdlib/base-image；原wheel字节hash/size/provenance；安装文件及native/system动态依赖；import/.pth/pyc/generated策略。对接现 `SmolLmNeuralReadConfigV1`/execution-profile binding，禁止只接受无权路径或六projectsource代替runtime。 | 不静默改旧11角色/300MiB、旧digest或验收。原版本继续拒绝额外roles，runtime新契约必须显式review；单object超过cache时以现chunk方案有界消费，不豁免上限。实际manifest及所有字节齐全前拒绝运行 |
| 2 / M09 fetch与materialize | 原fetch/materializer消费runtime manifest与原材料，返回只由本地原owner构造的admitted、private、held runtime+material namespace。接入同owner destination/cache/DB/WAL/SHM/scratch/oldversion/UNKNOWN reservation与persistent-retention ledger；每一退休由真实终态/持有解除证明。 | 首先完整peak/sourcebinding admission，再创建有限目的根。错误、crash、换目录、缺库/缺wheel、cacheevict时仍需回读、full-disk/权限拒绝均failclosed且不能refundUNKNOWN。持久/repair不得只留临时DB或digest清单 |
| 3 / 原真实loader/FinalUse | 将已admit根的内容身份与loader实际open/import namespace绑定，明确可使用的interpreter/stdlib/native libs/环境；继续原signedResource/FinalUse/CURRENT窗口、参数、Ready和actualforward检查。对未知ambient或线上fallback拒绝；继续原shutdown/真实child终态。 | 新鲜目的端起始没有环境/模型cache，离线只能使用release。记录全部 acquisition/installation/firstactualforward 的 bytes、time、peak与source/runtime/parent身份。原35s十一材料cohort单独保留，完整cold计时另报，不能把预装环境结果冒cold |
| 4 / I10与普通任务 | 接原selector/evaluation/artifact/TaskFlow/资源owner的真实安装接口，再下一任务从原CURRENT读回实际安装parent；不是把VerifiedCellMaterial转换成安装权限。 | 三轮必须逐轮actualparent→train→evaluate→跨节点download→authorizedinstall→nextordinaryread；机械闭合与实际收益分别判定，零收益保留拒绝升级。原撤销/reorg/latecancel/denial/ownerterminal与预算断言不降格 |
| 5 / PN5原验收 | 在完整release/custody/repair已经闭合后才用既定三个独立管理员与故障域72hWAN方案。 | 同adminLAN、loopback、成功checkpoint不能替代；Pocket原UNKNOWN/1GiB NETWORK charge和FAIL完整保留。量测确认goodput/coldload/repair/recovery原cohorts，不从名义TPS推断 |

本次独立审阅完成，目标工作仍ACTIVE：complete cold release、ordinary installation、三轮收益、Windows原隔离与四路资格、独立WAN均保持未完成，merge_ready/task_complete=false。精确输入、源行、原失败和本次唯一小型只读SSH收据由同目录JSON绑定。
