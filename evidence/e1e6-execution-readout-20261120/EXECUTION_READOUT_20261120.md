# Hepta / Trillionnium 原实验执行与审计读回

**已有可验证的训练与执行基础设施，也发生了真实参数更新；尚无证据证明它已形成能随用户增长而自发增强、综合多模型长处的 foundation model。** E1–E5 的学习与规模主张仍未通过原门槛，Chain 原服务门槛也未过。E6 最后绑定的诊断 native 管线为 FAIL：组件、Root 控制和机制父的局部通过，没有转为完整 ordinary 父、Cold、Adopt 或结算资格。

报告编制与本次云端证据读回本身不新增实验；整轮审计中的实际训练、模型调用、native 执行和源码对象创建按各阶段记账。本报告的最终执行截面选择 `8ce582b0a8619ff9250bc3a0098456112110ef82` / tree `698ebaaf9cd8706a1850e2531aeb0bc2c37a1f25` / inventory `019cee0f93b88145076b4a837c2bbdfdbd77181eeafa91dd35e622b1ace41d72`。其 R3 编译及项目 lint 实际 PASS，完整源码门 PASS，source freeze PASS；完整 NoUpdate15 父实际失败。下列 41a / NoUpdate14 与诊断 R1 记录均为历史阶段，旧失败保留，后继结果不倒写原件。

## 一、E1–E5 的科学结果

| 实验 | 已实际完成 | 原门槛下的结论 |
|---|---|---|
| E1 / E2：轨迹模仿与有效反馈 | 两学生各 32 次更新后冻结；后续共享评测 56 次模型调用、47 次 native 执行、9 次准入拒绝。四题 future 面板固定后未换题 | future 三个模式均零成功；native feedback 未超过 document evidence。维持 Research NoUpdate，未证明未来泛化或反馈额外收益；旧能力保留仍按原退化阈值验收 |
| E3：教师互补 | 原 T1 复用 12 次、T2 新 12 次调用；六题 union 为 1/6，与最佳教师相同 | 互补增益为零。新 SmolLM2 材料仍缺完整权重，不能计为已可用教师或新互补证据 |
| E4：多 Cell 组合 | 已曝光 B2 上运行同两调用上限的 PP / CC / PC / CP 等对照；后续共 112 次模型调用、118 次 verifier | 四种组合 selected 都为 5/6，混合组合未超过同模型对照；不是末次回答都为 5/6，也不能把跨臂 oracle union 当真实路由成绩 |
| E5：来源增长 | 公共维护者材料扩到 16 项；无损材料、原测试和 before-only 有界视图均保留。v2 有七项完整编码满足字节/token 限制 | v2 的原静态准入及训练准入均为 0，固定 1/4/16 前缀全部 false；v1 的 attrs 单来源静态准入保留，不授予前缀或训练资格。16 个公共项目不等于 16 个用户，290 个原测试身份不等于训练次数 |

以上来自 [E1/E2 冻结训练原件](references/raw-training--TRAINING_READOUT.json)、[56 次评测与原决策](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/ef096991a2632d04758d5a577ea9fbdf54209d31/qualification/cell-upstream-raw-function-learning-20261119/evaluation-20261120/READOUT.json)、[原 E3 读回](references/e3-original--READOUT.json)、[E4 与原历史字段](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/a5366ae2e16f1ed77273bc610671b580ecc0eaf0/qualification/cell-joint-20261118-2e9b/CURRENT_PROGRESS.json) 和 [E5 最终计量](references/e5-v2--MEASUREMENT_READOUT_3.json)。

关键预算继续保留：该 56 次评测阶段复用此前已训练并冻结的权重，不再算一轮训练；E5 仍为输入 4096、完整序列 3584、target 384 token、消息 65536 B，增长曲线分别为固定总量 32 units 和每来源 32 units。不能通过重排来源、截断完整目标、改准入标志或追加未冻结调用来把负结果改成正结果。以首个 loguru 为例，原 v1 契约要求展示的 fixture 已达 82,736 B，单项就超过消息预算；新的局部表示需要自己的冻结身份与实测。[E5 可行性边界](references/e5-next--READOUT.md)

### 保留的原预算、历史结果和可执行阻断

旧 E1 的 128 updates / 96 模型调用 / 96 评测 verifier 调用（另有 freeze-reference 与 training-reference 各 12 次）、旧 E2 两臂各 64 updates；108 次模型评测及 108 次 verifier 调用，其中 71 次进入业务执行、37 次格式拒绝，以及旧 E4 的 124 模型调用 / 130 verifier 都保留各自实验身份，不能与后来的 56 次、112 次评测合并成一个更好分数。旧 E1 的两臂 A selected 分别为 5/6、3/6，末次均为 2/6，B 均为 0/6，旧 E2 的 B2 两臂末次均 3/6，已有退化与 NoUpdate 结论不被新表示层覆盖；E4 跨臂 oracle 6/6 不是实际路由得到的 6/6。具体冻结字段仍见前述 joint CURRENT 原件。

E1 / E2 该轮 56 次调用已全部用完；已曝光 future 不能用来重选题、调 target 或给旧学生追加调用。E3 原 T2 的 12 新调用已耗尽，maintenance 的 8 次另有历史身份；该 T2 的内部 private 使用授权与 upstream / local license 标识冲突仍需按原限制处理，不把其输出转为训练材料。新增 SmolLM2 只收到 901,316,608 个唯一权重字节、尚缺 2,521,461,344 B，已有 Qwen2 runtime 对具体 Smol 的 Llama 配置也未准入；这不是新增“必须 Llama 家族”的验收条件。E4 的已曝光对照没有证实消息增益，下一轮不能沿用其结果作未曝光确认。E5 当前 v2 的 16 个公开来源没有满足原静态准入；v1 曾有 ordinal11（第12个来源）attrs 的孤立静态准入，原固定前缀和训练准入仍未通过，64 来源点仍缺 48 个真实来源，训练、预算映射和 future 验收仍未启动。这里列的是当前原实验的预算、材料、许可或准入阻断；没有据此宣称所有后续工程都不可能执行。

## 二、E6：按源码阶段区分局部物证、完整父与后续资格

`dbd6a009…` 的 NoUpdate12 留存物证确认：28 参数 Q24 模型执行两步 SGD，两个权重坐标改变；独立 B 按原阴性 fixture 拒用较差候选，保留基线。六阶段 terminal、七组物理 journal cut、六个实际签名槽和首次 Root acceptance / typed ACK 相互一致。但原整体测试随后在 C Generation drain 断言失败。这是小型 Q24 协议训练和拒用控制，不是 E1/E2 的 LLM 泛化试验，更不授予冷恢复、最终使用或结算资格。[实际 Training / B / ACK 物理读回](../e6-observation-diagnostic-runtime-20261120/training-business-data/READOUT.md)

后继 `1a979968…` 的 C 同步 drain 修复实际通过编译、lint、53 模块 / 468 cases、908 protected、452 targeted、完整 1164 caller CLI，以及原七项 blob 控制和完整 156 路径门。原 native 的 18 个 framing 组件、47 个原组件、两个 UID0 Root 组件和 Root 机制父也通过；**真正 NoUpdate13 父仍为 1 FAIL**。它在更早的 startup 并发路径触发 Historical lane 竞争与 fence，未到达新 C drain，因此不能用本轮评价 drain 修复已成功。[1a979 实际阶段与完整失败范围](references/final-startup-successor/a03c14f2e153a35e3ce7-ACTUAL_1A979_SECTION.md)

此前 41a startup 阶段的候选将原 source preflight 放在 delivery 创建之前完成，再由私有 Prepared consumer 消费；原权限检查、取消、恢复、try-lock/fence、64 上限与时限继续保留。七源码候选的六项 focused Python 控制通过，实际 fmt 零变化，`rebind={}`。首轮原编译命令确实启动，但在 nextest workspace metadata 阶段因额外锁定依赖缺件退出 102；该历史失败及已消耗的 0.665944250 秒原编译工作预算保留。补齐材料后的实际编译和后续执行另列于下，不覆盖这次失败。[实际格式身份](references/final-startup-successor/d3c5c2bf7a5a98ee7a1b-READOUT.json)、[编译失败原件](references/final-startup-successor/03cc0ae10d73fdf0c252-ROOT_ACTUAL_FAILURE_READBACK.json)

环境恢复成本单列：原 1090 包恢复成功用了两个 owner 共 578.817415390 秒；补充 workspace 全锁所缺的 225 包首次尝试用了 3.008905327 秒，在 Git 材料独立存储检查失败，**0 GET / 0 新 body**。六条只读 source Git 已实际消耗，累计为 86；source 与 target 未变，该次尚无 1315 seal。其后限定 35 路径 lstat 只证明 20 项 stat 不变、15 项仅 nlink 1→2 与 ctime 变化，没有读取正文或证明实际 alias、操作者。Cargo 原实现支持某种 hardlink 机制，不等于本次因果已证。其后材料终态见下文 OUT3；材料成本与后续 build、native 结果分开。[真实失败及预算](references/final-startup-successor/6a425a1258556d9ea8ce-ROOT_ACTUAL_FAILURE_READBACK.json)、[限定元数据读回](references/final-startup-successor/c3b9ca933efad0f18bff-ROOT_LOCAL_ACTUAL_READBACK.json)

补充材料的第二次实际尝试为 **FAIL**：新增 198 次 GET，完整核验 194 个额外包，owner 为 67.063447436 秒；在广告长度边界检查停止，原日志没有保存此前 GET 的确切 Content-Length。已有 1090 成功封存继续保留，194 个新增包不等于完整 1315 seal，也不产生编译或 native 资格。[第二次补充材料实际 RESULT](references/final-startup-successor/9e50c66f8df48baa635e-RESULT.json)

随后独立 HEAD 探测实际只做 1 次 HEAD、0 次 GET、返回 body 0 B；当前响应广告长度为 36296166 B，owner 1.314745839 秒。这是后来的响应，不能重构旧 GET 的响应。有限 alias 证明已逐件绑定 15 个原对象及其私有名称，20 个其余元数据保持；它证明指定范围的当前文件关系，不证明由谁或何时形成，也不是新的材料权限。[实际 HEAD](references/final-startup-successor/0fcc0eafbd209cf9dfd3-RESULT.json)、[有限 alias 实证](references/final-startup-successor/268db485172935e10c10-ROOT_ACTUAL_SUCCESS_READBACK.json)

NoUpdate14 模板的独立复核保留原 18 + 47 组件、两个 Root 控制、机制父、整父、预算和重试参数；只修正新 run_id，并移除新增的 compiler 源文件单链接限制。原 Cargo 主源允许合法输出硬链接；单独运行 pin 的单链接 / 0555 / 身份检查仍保留。模板审查不能替代材料、真实新 target、两个实际 ELF、完整门或 native 结果。[rev4 静态边界](references/final-startup-successor/41cbd2d7255a5a4ee3e5-READOUT.json)

补充材料 OUT3 已实际 **PASS**：本 owner 31 次 GET / 31 complete，复用并重新核验此前 194 项；全部 1315 个锁定包、1169 个 index entries 与 5 个 Git 材料仓已形成新 seal。owner 为 13.734203790 秒，累计 GET 1323、返回 body 269813733 B、Git 命令 98。原 1090 范围两次恢复的 578.817415390 秒及额外 225 范围此前失败分别保留；OUT3 没有执行编译或 native。source / target 在其本轮前后均未变。[OUT3 实际 RESULT](references/final-startup-successor/31257cd47b3deceaea67-RESULT.json)、[完整 seal](references/final-startup-successor/a2015e9696e618ea536c-MATERIAL_SEAL.json)

七份已格式化源码已另有不可变 source object `41a0fd9bbbc30051f1e7492cd17eeeb5337aa7a0`，tree `ea62214ae90a4b1f5e47d9690694c234521746dd`，parent 为原 `1a9799686243c2be0ee393ba364e091029cfb944`。对象创建时只绑定原七份格式化字节，没有移动远端 ref。其后实际编译、源码门、freeze 与 native 结果见下文；对象创建本身不授予这些资格。最终发布状态另由 exact ref 读回与 sidecar 确认。[未引用 source 身份](references/final-startup-successor/4f0d683af9b93043488e-UNREFERENCED_SOURCE_REVIEW.json)

### 历史阶段：41a 的实际源码资格和 NoUpdate14 终态

材料成功之后，原 [独立 owner 启动记录](references/final-startup-successor/421185847e14211ea2af-OWNER_START.json) 已有真实终态。以下均绑定同一 41a 源码、ea62214 tree 与 e5a6990d 全库存；这里的 PASS 只限表中相应阶段。

| 阶段 | 实际结果 | 证据范围与成本 |
|---|---|---|
| 新隔离 target 的编译 / 原项目 lint | PASS | compile 408.186323798 秒，justfix 301.051698583 秒，owner 715.963523158 秒；含首轮失败的原 compile 工作累计 408.852268048 秒，原 1800 秒预算不重置。实际两 ELF 与 15813 源库存保持 current，format/lint 无非预期字节变化 |
| 完整原源码门 | PASS | 54 模块 / 474 cases，908 protected occurrences，453 targeted 含原 452，完整 1165 caller CLI；owner 704.014650571 秒 |
| 精确 source freeze | PASS | 原 7 项 blob 控制、d83→41a 完整 158 路径 / 512000 B 门；owner 1.853668765 秒。不是尚未创建的最终 evidence head 门 |
| 首次 native owner | 29 个组件 PASS 后预检停止 | framing18 + scope11 通过；retirement16 在测试启动前因旧 inode 绑定断言停止，整父实际 0 次。owner 129.694123158 秒；不是一次 NoUpdate14 父失败 |
| 相同源码的有限接续 | 剩余 36 个组件、Root 2 项与机制 1 项 PASS；完整管线 FAIL | 原 29 项不重跑，合计 65 个不同组件；真实整父执行 1 次，1 FAIL / 0 error / 0 skip，case 9.016000000 秒 |

[编译与 lint 原 RESULT](references/final-startup-successor/c63db3795c8292dad396-RESULT.json)、[源码门原 RESULT](references/final-startup-successor/815d205ba90b95b3f11a-RESULT.json)、[四份完整门正文独立核验](references/final-startup-successor/b7e639e5e0afc9a2edfd-ROOT_CONTENT_REVIEW.json)、[source freeze](references/final-startup-successor/68c74c306c246a019898-RESULT.json)、[首次 owner 预检失败](references/final-startup-successor/72199c3acc755bec10a9-READBACK.json)、[接续真实终态](references/final-startup-successor/6dfaefae555096297101-READBACK.json)、[Root 独立全结果复核](references/final-startup-successor/ba5803b435e2d2eb4ef3-ROOT_TERMINAL_REVIEW.json)。

首次预检失败只涉及跨 Cargo 执行后旧 inode 身份假设，实际 ELF 全字节 SHA、长度与 mode 相同；接续保留新 target、只读 pin 和稳定 FD 身份检查，没有改变产品源码，也没有把已经通过的 29 项再算一次。接续 pipeline owner 为 286.523770981 秒，其中完整 wrapper 为 242.775565415 秒；case、命令、wrapper 与 pipeline 是嵌套区间，不能相加成独立总成本。

父在初始 A 收尾时等待 Root 成功退出失败；Root 内部 header-write 错误的发生时刻未知：A 的 Objective receipt、publish、observe、RunStart 已返回，独立 observer 也 PASS；Root 留下 `peer.response-header-write ThreadId(14) → observation.exchange → lane.observation → cli.serve → Unavailable`。B / C 尚未进入。此前 ready exchange 的 62.705 ms 是成功就绪耗时，不是错误发生时间；另外的 control ACK lost 也不能直接认作同一 socket 的首因。完整六份 stdio 已保留，共 16,584 B；错误 errno、revents 及两端关闭先后仍未由当前原件确定。[六份实际 stdio 清单](references/final-startup-successor/089c3345c451a2ea69b2-MANIFEST.json)、[header-write 有限源码诊断](references/final-startup-successor/ba0eae85ccfc0b44d0fe-README.md)、[原标签更正补遗](references/final-startup-successor/f2d3f2a099ebb8823d16-SOURCE_ANCHOR_CORRECTION.json)。

独立 exact41a 调用链审查证明：原父先等待 `run_original_a` 成功返回，才构造并启动 post-A；A 的 Objective、observer、daemon 与 Root 成功退出、Source pin 检查均在这个返回之前。A 走 `q24-initial / InitialQ24` 分支，Post-A assembler 对该 variant 在构造前返回。因此此次新增 `prepare-before-delivery` 不可能已经在这条初始 A 路径直接执行。这个静态可达性结论不证明 header-write 根因，也不排除二进制布局、环境或调度的间接影响。[时序与 variant 双重边界](references/final-startup-successor/a555dfb4501cf7f24e76-README.md)

完整 wrapper 的 86 个逻辑原件 / 11596846 B 已按原 inventory 全部读回，包含 Root 三项 stdout/native、helper/product JSONL、launch、roster、budgets 和 cleanup；逐 SHA、固定 version 与 EOF 检查通过。已有原件复用与新读取分别记账，完整 RPC 保留。四份此前只有 file_info 的门正文也已全部补齐；旧“正文待回收”的阶段性读回记录仍保留，不能当当前缺口。[wrapper 全量读回](references/final-startup-successor/9bc28d5036f2a4421ed9-READBACK.json)

### 历史阶段：两端 I/O 诊断 R1 的格式化与不可写输出失败

NoUpdate14 的原失败保留。新候选只增加两端 I/O 诊断：在原错误分类与 fence / shutdown / restore 顺序之外记录有限错误信息，区分返回错误与未完成 future 的释放。未完成 future 的释放不自动证明取消；新增日志也不是传输缺陷已经修复的证据。四份 Rust 和两份 policy 文件的完整差异、权限边界与同步日志开销限制均已静态审查；原 deadline、64 帧、组件集合与重试要求不改变。[原候选与 Root 静态审查](references/final-startup-successor/db9668e0f5051b6038d8-ROOT_STATIC_REVIEW.json)、[独立诊断 peer](references/final-startup-successor/2dc578dc9a82b18e5aa6-README.md)

原 `just fmt` 实际 PASS，命令 0.364365116 秒、owner 5.838131007 秒；只对三份 Rust 产生排版变化。candidate2 的四份 Rust 逐字等于实际格式化输出，随后只把两条 protected occurrence 中的三处 literal 与 allowlist 的 CALLERS 摘要精确重绑，其余 906 条原始 occurrence 及全部 required / forbidden 条件保留。应用两份 policy 后的本云库存投影为 `25d8b9cc…`；后来的编译原件确认其前后摘要相同，完整 JSON 通过既有完整字节精确重构并与实际 file_info 的大小及 SHA 匹配，不冒称重新下载正文。[实际格式化 RESULT](references/final-startup-successor/91bdcd9b55fc9af2903c-RESULT.json)、[精确格式重绑](references/final-startup-successor/ad047c6392d3bd93466b-POLICY_FORMAT_REBIND.json)

这六份源码已绑定不可变对象 `1f672df3472cc6534ff267fbec9b626a3d710fe6` / tree `10a995ef976a74fddf2d8653b42398c9390307c6`，parent 为 41a；对象创建时没有移动远端 ref。对象身份与实际格式化不授予编译、源码门、native 或传输修复资格。[诊断 source 对象身份](references/final-startup-successor/728ab42b45624bb87728-UNREFERENCED_SOURCE_REVIEW.json)

编译模板中的历史 null 字段保持原样；独立 EXECUTION_MANIFEST / META / payload 完成实际绑定后，Root 授权的唯一 owner 于 **2026-11-20 20:34:38.508 UTC** 启动。该启动观察与后来的真实终态分开保存：诊断 R1 此次编译 FAIL，原命令退出 101，消耗 168.582855377 秒，owner 172.064058134 秒；同候选原 1800 秒 compile 工作预算剩 1631.417144623 秒。完整 stderr 的直接报错为测试输出 ELF `is not writeable -- check its permissions`。现有 ELF 的 file_info 显示 mode 0555、既有字节 SHA 不变；这些事实尚不能证明完整权限/进程因果，也不是已证 Rust 类型错误或原 transport 错误根因。在该 R1 owner 内，justfix、源码门、native 均未开始，源码前后均为 25d8；后来的 R2 / R3 编译与源码门另列于下。2 jobs、locked / offline 与原预算不变，既有 41a 资格不迁移。[Root 精确执行审查](references/final-startup-successor/c6ed9e00fc5e407e76e9-ROOT_EXECUTION_REVIEW.json)、[实际 owner 启动](references/final-startup-successor/fe004165902e02bfea99-OWNER_START.json)、[模板 peer](references/final-startup-successor/39ce4b0202093812ad29-README.md)、[实际绑定补遗](references/final-startup-successor/1dcf47d7b05350fedb7b-README.md)、[编译失败 RESULT](references/final-startup-successor/9fe542b7e88698fff499-RESULT.json)、[完整 stderr](references/final-startup-successor/fadcd8dd12c004ad6173-compile.stderr)、[终态与剩余预算读回](references/final-startup-successor/168e9c7574ea6c729e0e-READBACK.json)、[输出 ELF 元数据](references/final-startup-successor/41f9d250014cc75ecc6f-ACTUAL_FAILED_ELF_FILE_INFO.json)

### 诊断收口接续：R2 与 source5 R3 的实际结果

针对自有输出 ELF 的有限 mode 恢复经单独审查后，1f672 的 R2 实际 PASS：compile 68.576839101 秒、justfix 136.582347845 秒、enclosing owner 210.187682780 秒。加上保留的 R1 失败，原 compile 工作累计 237.159694478 秒。四个只读进程观察 unknown 仍保持未知，编译通过不把它们改写成已证明不存在。[R2 完整实际 RESULT](references/final-startup-successor/80ad206fb12b90997072-RESULT.json)、[原 mode 范围审查](references/final-startup-successor/15125b2885e52b5c5937-README.md)

随后 1f672 的完整原源码门实际 FAIL：54 模块 / 474 cases 中 0 failure、12 errors；908 protected 中两处新增序列写法与原 verifier 的最短序列及 code-mask 规则不兼容。460 targeted 通过，完整 caller CLI 没有启动，125 是未启动占位退出值；owner 235.655765521 秒。12 个错误是两处基线验证失败在原 mutation tests 中重复出现，不能写成 12 个独立产品缺陷，更不能把 targeted 通过当整门通过。[原失败 RESULT](references/final-startup-successor/3e1af2929b6ec08baf9e-RESULT.json)、[完整失败读回](references/final-startup-successor/77668472add1f2f8ca1c-READBACK.json)、[独立原因复核](references/final-startup-successor/1bfb01aa6bd19373ab83-READOUT.json)

candidate3 只修两份 policy 与一个原 QA 的函数定位，四份 Rust 保持实际格式化字节；原 13 个 case、三个检查标记及每个 mutation 均保留。该原模块实际 13 项通过，6.328664746 秒；这不替代完整 54 模块门。三文件 delta 形成 source5 `8ce582b0a8619ff9250bc3a0098456112110ef82` / tree `698ebaaf9cd8706a1850e2531aeb0bc2c37a1f25`，parent 为 1f672，创建对象时没有移动远端 ref。[原模块控制 RESULT](references/final-startup-successor/7019d25f3afb96415b44-RESULT.json)、[Root 候选范围复核](references/final-startup-successor/be45afba5bd5cc4d4f53-ROOT_CANDIDATE3_READY.json)、[source5 对象身份](references/final-startup-successor/3bede4b689a9d674cf69-UNREFERENCED_SOURCE_REVIEW.json)

R3 应用这三文件 delta 后，以完整库存 019cee 执行原编译和项目 lint，实际 PASS：compile 95.620355472 秒、justfix 105.127914425 秒、enclosing owner 204.426524972 秒。原 compile 工作累计 332.780049950 秒，项目 lint 累计 241.710262270 秒；各原 1800 秒工作预算不重置。编译与 lint 期间的 source / ELF current 检查通过，不声称整个 owner 没有应用审阅过的源码 delta。旧 1f 的成功与失败仍保留在自己的身份下，不能代替 8ce 的门和 native。[R3 完整实际 RESULT](references/final-startup-successor/2a0a3689819bf7440fe5-RESULT.json)、[R3 完整日志读回](references/final-startup-successor/370f7dfc58d8ed7238d2-READBACK.json)、[Root 精确 R3 执行范围](references/final-startup-successor/23a41ffc8792ec31b710-ROOT_EXECUTION_REVIEW.json)

| source5 后续阶段 | 最终实际绑定 |
|---|---|
| 完整原源码门 | PASS |
| source freeze 与原 7 项 / 完整 PR blob 门 | PASS |
| 诊断 native15 管线与其完整父范围 | FAIL |

这三个阶段均已绑定到同一 selected source 的实际 RESULT、原 owner 启动、完整终态 PTY 与固定版本读回。源码门完成 54 模块 / 474 cases、908 protected、460 targeted 和完整 1165 caller CLI；source freeze 的原 7 项及完整 d83→8ce 的 162 个 changed paths / 512000 B blob 门通过。这里的 source-head 门不代替后继 source+evidence 最终提交的完整 PR 门。旧 41a / 1f 运行保留自己的身份，资格不迁移。[gate3 精确执行绑定](references/final-startup-successor/774c3bed1583bf0ee129-ROOT_EXECUTION_REVIEW.json)、[gate3 原 owner 启动观察](references/final-startup-successor/8412c4fc5315adcc3841-OWNER_START.json)、[gate3 完整实际 RESULT](references/final-startup-successor/37fdeef3466f56e35939-RESULT.json)、[freeze2 实际 RESULT](references/final-startup-successor/b84064b52ccd811d00d3-RESULT.json)

### 最终执行截面：NoUpdate15 到达完成验收后失败

原 7 组共 65 个唯一组件用例通过；两个 Root completion 控制中 2 项通过，Root lane 机制父 1 项通过。真正完整 ordinary 父确实进入并执行 1 次，结果为 1 FAIL、0 error、0 skip，未自动重试。组件和 Root 通过没有覆盖这个完整父失败。[实际组件与唯一 case 读回](references/final-startup-successor/532255c79ffdea45530f-READBACK.json)、[完整 native/wrapper/父终态交接](references/final-startup-successor/ea54df12bd857d4f3164-TERMINAL_HANDOFF.json)、[Root 全原件独立复核](references/final-startup-successor/3e0d4928c8646484b528-ROOT_FULL_ORIGINALS_REVIEW.json)

A 的 observer 与局部 Objective 已完成，独立 B source child 通过；post-A 日志有 Training、Evaluation、Selection、NextUse 阶段。C 局部 receipt、publish、observe、final RunStart 有返回，随后 historical 请求连续到第 64 次 `runtime.learning.completed-acceptance.v1`，Root handler 在完成验收 action 内返回错误。父报告 `original complete historical task read unavailable`。该 action 包含多项任务/profile、B、publication、journal、签名和 postcheck，原始内层错误被统一映射为 `Unavailable`；现有标签不能确定是哪项检查失败。没有请求65或本轮 header-write 标签，亦不能据此宣布旧 header-write 根因已修。C 局部返回不等于 first acceptance ACK、退出后的 C 完整验收或 cold D；本轮新增 cold 0、Adopt 0，cold 因完整 ordinary 前提未通过而没有启动。[12 份实际 stdio 与捕获原件](references/final-startup-successor/937d05cf1854f0dbf8b7-MANIFEST.json)、[完成验收有限独立复核](references/final-startup-successor/81de2587e2bc3782a1a0-README.md)

计时分别保留：testcase 99.065 秒、原命令 99.796003537 秒、wrapper 234.241484142 秒、pipeline 375.556947290 秒；这些范围嵌套，不能相加。源码、tracked、compiler 和 pinned binary 身份保持；挂载 cleanup 为 PASS，原单 owned ELF 的 build-mode 恢复为 PASS。完整 wrapper inventory 的 89 个原件、7 组组件的完整结果/日志/协议/driver、全部终态 PTY 和 12 份子进程 stdio 均按固定身份留存；旧 body 复用与新增读取不混计。[wrapper 全量原件读回](references/final-startup-successor/33847dd37e84a513afc1-READBACK.json)

归档工具另作有限修复：终态识别绑定真实 owner 与完整 RESULT，source check 不得借另一 RESULT；原14与新15两份实际 bytecode 仅按各自完整路径、长度、SHA 和 Git blob 身份作为惰性数据保留，不导入或执行。v2 漏拒顶层 commit 矛盾的工具失败与 v3 修复后的有限工具 PASS 同时保存；v4 只增加新15精确身份，两个 reader 的原字节读取及错误长度拒绝共四项工具控制通过。归档工具或恢复成功不会把 E6 native FAIL 改成 PASS，也不增加模型调用或业务资格。[实际工具控制及保留负例](references/final-startup-successor/45790ba526ed06420120-READOUT.json)、[新15惰性原件的四项有限读取控制](references/final-startup-successor/dbc7ca3195ec95232ee2-READBACK.json)

### Cold、Adopt 与实际结算仍分别未闭合

原 [Cold 条件映射](references/final-startup-successor/a43d88e1c42851b2c574-README.md) 和 [当时缺件记录](references/final-startup-successor/3d284108c782ba75290f-PENDING_INPUTS_AND_CONFLICTS.json) 保留；后续已实际取得 cold QA 与其余 before 共 12 件，完成单 QA 三方合并和本云 81 个 selected source 候选。该候选 composed 表实际为 1220 boundaries / 928 protected occurrences，原 55 个 cold-only rows、36 cold 原件及既定三处 D 身份 delta 均保留。然而四个新文件 absence 只收到工具错误，当前仍有 4 个未证明的 absence；完整 cold repository inventory / commit 尚未绑定，cold compile、原门、native 共 0。这不是完整 cold repo 或已执行资格；600 / 300 / 120 / 480 与原 64 限制没有修改。[实际 before 与 81 文件候选读回](references/final-startup-successor/bb1a209901c37b23c871-READBACK.json)、[Root 静态核对](references/final-startup-successor/820ff97593cf301f5350-ROOT_STATIC_REVIEW.json)

普通 Adopt 的限定本云复核仍未找到一套同时保留每个 effect 前后完整 A 物理 Source / Cell / RunStart / terminal / refusal / live authority 条件、并实际不超过 64 帧的实现。当前原调用表给出条件性 74；即使假设两组 DATA 读回能安全合并，70 也只是未经证明的乐观算术。工厂 live lease、撤销和 B 检查确实存在，但其传递覆盖完整 A 历史观察的等价性没有证明；不能删除 Root 实体复核或跨外部 await 共享旧凭据来凑预算。这是当前有限证据的实现阻断，不是数学上的普遍不可能，也不是已执行 Adopt 结果。[有限 33 原件复核](references/final-startup-successor/1ef3d833fcfc8a05e607-README.md)

实际结算仍未绑定到本轮同 operation 的原凭据或原结算主测试。仓库确有 AuthBus signed quota settlement、Bao 产品组合，以及 Chain 原生 paid Task observer；FinalUse 的 40 B epoch/nonce 消耗不能替代付款。现有跨仓学习 business reader 仍 DENY_ALL / HOLD_NO_GO，两条保留学习例的 economics 为空，没有原 funded request/result mapping；即使以后 ordinary/cold 原父通过，也不自动升级 settlement。[实际结算职责和原入口](references/final-startup-successor/ea6881e2f0365054e365-README.md)、[结算证据范围](references/final-startup-successor/257255e55064630abf2f-READOUT.json)、[Root 独立范围复核](references/final-startup-successor/3c3f8eff2f2a58273317-ROOT_SCOPE_REVIEW.json)

所有历史负结果继续有效：bfea NoUpdate9 的路径错误、527e 新 namespace 控制失败且父未启动、9df NoUpdate11 的退出失败、dbd6 NoUpdate12 的 C drain 失败、1a979 NoUpdate13 的 startup 失败，以及 41a 首次预检失败 / 接续 NoUpdate14 A Root 退出失败、诊断 R1 不可写输出失败、1f 源码门实际失败和 8ce NoUpdate15 完成验收失败。第一轮物理 capture 的 JSONDecodeError 失败保留；随后查见零字节占位，第二轮只修正对零字节的处理，旧日志没有确定原错误路径，不能把该占位写成已证明首因。没有新的 native Adopt、cold D、完整 FinalUse、结算或生产采用。普通 Adopt 的静态调用预算仍有条件性 74 对 64 的缺口；未经证明的操作合并不能为了凑数字删除每个 effect 所需的真实权限观察。[Adopt 等价性边界](references/final-startup-successor/e2680ebfe3149cd1eb89-ADDENDUM.md)

## 三、代码成果与 Chain 边界

已经落到具体代码和原件的成果包括：计数整合修复及 114 项控制；16 来源无损材料和稳定动作/有界检索表示；E6 合法完成路径的 reader 与真实签名形状处理、namespace fixture 修正和同步 drain；Chain 针对本次新 native refusal 的延迟触发修复。各项资格仍按自己的确切源码、原门和实际执行范围计算。#6709 已在 joint `a536…`，E6 普通支线从 `bfea…` 分叉，不能把联合资格直接迁移过去。[计数控制原件](references/metrics-result--RESULT.json)、[联合原字段](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/a5366ae2e16f1ed77273bc610671b580ecc0eaf0/qualification/cell-joint-20261118-2e9b/CURRENT_PROGRESS.json)

Chain 的 W1 / body refusal / ROOT delay 原控制分别 6 / 3 / 4 项通过，mixed-service 的一个 named test 通过，完整 130 attempts 包含预期拒绝。原 F0 没有重跑，30 秒仍仅 1/6 确认、4 秒 0/6、及时 ACK 21/42；repository-truth 三个原门仍失败，完整物理成本未闭合。局部服务调度改善不构成原系统资格通过。[Chain 已发布原读回](https://github.com/TrillionniumFoundation/Trillionnium-Chain/blob/de5f5766fe44fdc42507afe14b30873060c9e4d2/evidence/chain-w1-delay-controls-20261120-e9e051/README.md)

## 四、对最初愿景的判断

HIA 有实际用途：表达调用、结果、取消和未知恢复的边界，避免隐式重放，并让已有 runtime owner 验证权限和 effect。审读的 Neural Circuit 代码把有界图编译到既有 TaskFlow 执行路径；本次静态读取不构成新的 circuit 运行结果，也不证明自动学出了高效通信或新智能。[HIA 原契约](references/hia-contract--hia_bridge.md)、[Circuit 原实现](references/circuit-source--cross_neural_circuit.rs)

要支持用户设想，还需要连续成立的三层结果：学生在未曝光任务上取得净增益且保留旧能力；稀疏路由与消息在相同调用、字节、延迟和验证成本下优于强单模型控制，并通过删边/置乱等因果检查；跨真实独立来源的更新最终进入共同学生，并经过真实采用、冷恢复和新任务使用。用户数、Cell 数、图的规模和训练量都不能替代这些证据。

PoUW 需要区分三类支付或信用：按原合同实际履约的 service fee，正确拒用候选的 NoUpdate 也可以获得；模型 improvement bonus 需要独立增益与完整可归属成本；consensus credit 还需要单独的安全性和攻击成本条件。付费、签名、训练量或任务有用都不能自动推出共识安全。当前完整成本与原生采用尚未闭合，因此不扩大结算或生产资格。[研究附录及原论文边界](research/RESEARCH_APPENDIX_20261120.md)

在保留的 **2026-11-20 20:11:27 UTC** 历史只读快照中，joint #6703 仍为 a536、E6 #6776 仍为 bfea，Chain #970 / #971 仍为 de5 / ea356，四项均 open / Draft / unmerged；该次没有重新读取其他 E5 PR。随后 **2026-11-20 21:20:45 UTC** 八项又已实际读取，head 均保持前值、open / Draft / unmerged；它仍是发布前阶段快照，最终 CAS 与实际发布门另由独立 sidecar 给出。原 [17:58 历史快照](references/final-startup-successor/e2427931ad9fcd0d0b7f-PR_REFRESH_WORKSPACE_RECOVERY_1.json)、[19:32 八项快照](references/final-startup-successor/c46974393deccbe234e1-PR_REFRESH_NATIVE14_ACTIVE_1.json) 与 [20:11 四项快照](references/final-startup-successor/937657c7b065b1387940-PR_REFRESH_NATIVE14_TERMINAL_2.json) 分别保留。599 条已上传对象收据不是最终 evidence commit 或 ref 已发布；41a 的实际 source gate 也不是未来 evidence head 的门。最终完整差异门必须针对届时 exact head 运行，回执保存在外部 sidecar / PR 正文，避免自指结论。 [21:20 八项原快照](references/final-startup-successor/46bfe1beb19f1c2419f3-PR_REFRESH_DIAGNOSTIC_POLICY_1.json)、[本期 automation hold 原件](references/final-startup-successor/047448cf98b03baa5666-AUTOMATION_DIAGNOSTIC_POLICY_HOLD_2.json)。

概念分析引用的五篇 primary 已由 Root 再次打开，保留 [原始来源复核记录](references/final-startup-successor/b22577085b35f457596a-ROOT_PRIMARY_RECHECK_20261120.json)；论文的外部结果不作为本仓库实验成绩。本报告保留全部历史负结果，并以 selected8ce 的真实源码门、freeze 和 NoUpdate15 终态收口。最终 source+evidence Git 提交、精确完整 PR blob 门以及非 force ref 更新的结果另记于独立发布回执和 PR 正文，避免把尚未执行的 finalhead gate 写进被测提交。报告生成、原件归档与实验结果分别记账。

发布前最后保留的八个 PR 读回仍为 open / Draft / unmerged；两次 Chain transport error 与后续实际小型 GET 同时保留，不能把多个观察区间合成单个精确时刻。自动任务的最新真实 peek 在 22:07:19→22:07:20 UTC，enabled / hourly 与 hard hold 保持；它不授权额外 host 运行，最终发布后的交接另行记录。[八个 PR 的完整分段读回](references/final-startup-successor/08ad07a07f361cbce72b-PR_REFRESH_FINAL_PREPARATION_READBACK_1.json)、[最后实际自动任务 peek](references/final-startup-successor/f7454b0680d11f890c7f-AUTOMATION_FINAL_TERMINAL_PEEK_2.json)