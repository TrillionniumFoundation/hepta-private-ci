# E1–E6 联合推进：原始证据与当前边界

观察时间：2026-11-19 00:59:08 America/New_York（05:59:08 UTC）。
本页与 [CURRENT_PROGRESS.json](CURRENT_PROGRESS.json) 同步；上一证据提交为 `fbeeef0670219efe0a3939a9ccf982967feafb90`。原联合执行候选与历史 NoUpdate、失败、成本原件继续保留。各分支局部结果尚未合成为一套通过原资格门的能力。

**持续工作已产生新的真实原生证据，但完整采用、未来任务学习收益、Circuit 必要性和完整物理成本仍未通过。全部十项资格标记保持 false。**

## 当前进展

| 原实验／工作 | 最新实证 | 仍要闭合的原门 |
| --- | --- | --- |
| E1 轨迹价值 | 原独立96次调用／四臂结果仍为0/6；新材料沿原候选顺序、原许可和完整上下文筛选 | 未来任务上 frozen、retrieval、答案 SFT、轨迹 SFT 的同信息／同预算对照 |
| E2 学生自身经验 | 两臂各32次更新已完成并冻结真实权重。Mistune 与 Babel 的原参考修复、共同 codec/context/dedup 和许可保留检查成立 | 补齐四题面板并在冻结协议下实际运行更新后的学生；新未来模型调用仍为0 |
| E3 多教师互补 | 原 T2/P 对照保留；其结果不构成互补收益 | 真正不同且获准使用的教师、匹配工具／信息／计算、负迁移测量 |
| E4 Circuit | 原 B2 的 PP、CC、PC、CP 均为5/6；未优于强单模型 | 同预算多步自修复／检索／verifier 比较和消息／路由／Cell 消融 |
| E5 用户增长 | 原4个许可来源、83个 blob 和原生对照保留；已认证真实用户仍为0 | 固定总预算与固定每来源预算两条曲线，以及去重的真实来源扩充 |
| E6 完整采用 | bc16 原生组件11/11通过；完整 NoUpdate6 仍在第65次读被原64上限拒绝。新启动组合的223项源码测试与892条保护规则通过 | 完整1137调用边界、新候选原生组件、原 NoUpdate 全流程、新 C、冷恢复后的真正新 D、原 owner 采用 |
| Chain 活性／成本 | 新 e8b 唯一原 F0 已实际失败：30秒1/6、六个4秒目标0/6、及时 ACK21/42；原26个 CI 已全终态 | 原业务目标、数值耗尽要求、完整物理成本和后续真实性能候选 |

## E6：保持原64次读上限，组合原所有者的一次同步工作

Draft [#6726](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/6726) 的 bc16 原生组件实际执行11例，全部通过，0失败／跳过。命令耗时73.5435秒，owner耗时74.7235秒。随后原 NoUpdate6 父用例实际执行1例并失败，0跳过，命令耗时68.6102秒，owner耗时132.2272秒；源文件、产品固定摘要和清理检查保持完整。[组件原件](original-readbacks/20261119-0054/E6_NATIVE6_RESULT.json) · [完整父用例原件](original-readbacks/20261119-0054/E6_NOUPDATE6_RESULT.json)

完整轨迹显示，初始化阶段先耗用58次交换，Restore／Experience／Dataset 再用6次，Training 在第65次读被拒绝。新的13文件修复把以下同步构造放进其实际原 owner 操作中：Task／Ledger／Preparation、freeze 的打开／恢复／授权／materialize、历史 successor 的 context 与 slot 登记、历史 source 与 delivery bootstrap 构造，以及已初始化 Experience／Dataset 的真实回执和 checkpoint 读回。

所有原始 Root 身份、receipt、当前信任、完整 source、时限与操作后检查继续执行。新借用不跨异步等待；持久化 claim、训练、B 和 C 的独立操作检查继续存在。初始化新 witness 之前的物理 Root post-read 也继续保留。原验证器未修改，`MAX_READS=64` 和原时间窗口未改。

这组修复的库／二进制检查已通过。原223项源码测试、892条受保护规则已通过；251项受影响调用者扫描仍有两处接收者类型归属诊断，正在显式化后执行完整1137边界扫描。先前207项、223项检查中的失败原件均保留。当前还没有该新候选的 native7 或完整 NoUpdate7 结果。[编译原件](original-readbacks/20261119-0054/E6_STARTUP_COMPILE6_RESULT.json) · [首轮契约迁移失败](original-readbacks/20261119-0054/E6_STARTUP_CONTRACT1_FAILURE.json)

### 完整原件已发布

证据提交 [ebb805](https://github.com/TrillionniumFoundation/hepta-private-ci/commit/ebb805baa373271bdff58a8c0774438a8b769e4e) 包含190份源门原件的3,006,828字节 archive，以及 native4／NoUpdate5 的1,202份原件、59,040,488字节 archive。后者分成七个精确片段，提供重组校验器；所有片段和完整 SHA256 均由 root 重新校验。原512000字节策略不变，只增加八条精确内容摘要例外。NoUpdate6 的 RESULT、XML、stdout 也已发布，完整运行目录归档仍待完成。

### 冷恢复 D

新完整 D 父用例已接入真实三个 handoff、新 Root／daemon、一次普通 Objective 提交、原 typed RunStart 恰好单帧追加、新 Source／Cell／Generation、CURRENT 从 C 到 D、独立新 FinalUse nonce 和原 consumer frontier 的实际读回。原只读冷恢复方法仍保留。八文件补丁已逐块复核，实际编译通过，耗时82.9301秒。[原编译结果](original-readbacks/20261119-0054/E6_COLD_D_HARNESS_COMPILE4_RESULT.json)

新的真实 Root store 组件在 `ce154d42` 执行1例并通过，0失败／跳过／重试，完整 owner耗时93.4259秒，源文件和产品字节未变，mount清理成功。覆盖原64次／第65次拒绝、两个同时 Armed 的不同操作、真实受保护 registry 的排他锁，以及同 identity 但不同原 registry／key 的跨 context 拒绝。首次尝试重开同一个受保护 registry 得到真实 StateLocked，失败原件已保留；后续通过原管理员接口新建第二个独立 registry。该组件没有执行 C、D 或 FinalUse issuer。[失败原件](original-readbacks/20261119-0054/E6_COLD_ROOT_STORE4_FAILURE.json) · [通过原件](original-readbacks/20261119-0054/E6_COLD_ROOT_STORE5_RESULT.json)

**真正新 D 执行仍为0。** Adopt 路径还有实际期限冲突：post-A CURRENT 的原240秒期限早于旧 writer 的300秒冷恢复等待结束。NoUpdate 初始 CURRENT 的原期限为600秒。后续需让真正原 owner 完成有效重新授权／入选，不能用新 D 签名把旧过期 CURRENT 视作有效；这些期限没有放宽。独立人类 controller 认证仍为0。

## E1–E3：权重先冻结，未来材料按原次序准入

Draft [#6737](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/6737) 的 document/native 两组真实权重已经完成：各32次更新、56个 forward/backward 步、10256个 target token、200704个 padded token，信息与计划计算形状对齐。权重冻结摘要为 `237ae92fc94d6ae411671c671190314049ded5cdc0d5dae254d57c9d8bb67be6`。原24次和56次布局实验的零收益及 NoUpdate 结果继续保留。

未来材料只根据预先公布的项目次序、每项目50个非 merge 提交、原函数变化和原完整测试选择。实际模型输出没有参与选择。当前 root 已逐字节读取并核验以下三个原对照：

| 原项目／函数 | 同一原 case 集 | 原 parent | 精确参考修复 | 后续准入 |
| --- | ---: | ---: | ---: | --- |
| Mistune／parse_footnote_item | 280 | 3失败 | 280通过 | 完整上下文、codec、去重及原许可保留检查通过 |
| Babel／unquote_string | 29 | 23失败 | 29通过 | 完整上下文、codec、去重及原许可保留检查通过 |
| Jinja／do_int | 132 | 1失败 | 132通过 | 完整固定上下文和共同第二次调用预留超预算，拒绝入选 |

三对都没有 error、skip 或 timeout，且都是参考函数验证，**没有新学生模型调用**。[Mistune 原件](original-readbacks/20261119-0054/MISTUNE_NATIVE_PAIR_RESULT.json) · [Babel 原件](original-readbacks/20261119-0054/BABEL_NATIVE_PAIR_RESULT.json) · [Jinja 原件及预算拒绝](original-readbacks/20261119-0054/JINJA_CONTEXT_RESULT.json)

Mistune 的首次上下文为1661 token，包含统一第二次调用预留的计划总数6013；Babel 为1426和5778。Jinja 拒绝后没有截断原测试、缩减反馈或改预算。两个项目在 parent、修复 commit 和冻结 HEAD 的18份原许可／声明已经绑定；六种不同原文已独立全文读取并核验，复制材料继续附带完整条件和声明。[许可保留记录](original-readbacks/20261119-0054/FUTURE_LICENSE_REVIEW.json)

原12项目池留下两项可用材料，四题面板尚未冻结。替补次序已在 `dfc8e89e` 先于其内容读取发布，从 wcwidth 继续，仍按原规则停止于四个不同项目。许可材料不计作真实用户，也不构成项目作者背书或私有教师授权。

### 成本测量的具体缺口

旧原生对照的 `completed_child_cpu_seconds` 来自外侧 bwrap 等待前后的 `RUSAGE_CHILDREN` 差值，没有测到完整内部 pytest CPU。旧数值与原件保持不变，不能当作完整原生 CPU。后续 v5 只增加内部进程成本观测，分别记录 self lifetime、entry delta 与已回收后代；这些范围有重叠，不相加冒充全系统 CPU。旧 pair 不为补成本重新执行。v5 变更仍待 root 源码复核，完整物理成本资格继续为 false。

## Chain：新唯一原 F0 仍未完成原业务目标

Draft [#970](https://github.com/TrillionniumFoundation/Trillionnium-Chain/pull/970) 的冻结源为 `e8b0ec93ab6a6a1ff5e36cfcf9d1179e030a5975`，tree为 `c896826d4f376d6643b05c15486f573e9aff6546`。它的133项原 authenticated 控制全部通过。另一个原512个无效产品控制实际失败：消耗298399949ns，原400000000ns额度剩101600051ns，尚高于100000000ns启动预留；294通过、1失败、2忽略的原结果完整保留，没有人为增加 CPU 消耗或改配额。

唯一原 F0 [44465153982](https://github.com/TrillionniumFoundation/Trillionnium-Chain/actions/runs/44465153982) 已终态。443份 manifest 原件和18,781,500字节 ZIP 全部核验：

- 原30秒确认目标：1/6；六个预定4秒目标：0/6。
- 及时网络 ACK：21/42；21个原计划包未实际尝试，ACK不作为业务确认。
- 原 business、全部4秒目标与 numeric depletion 三门都拒绝；native退出101。
- 清理实测 known-empty；原业务窗口、packet分母和额度没有改变。
- 完整物理存储／网络、全系统并发 RSS、GPU、能耗及费用仍未知。

[完整原读回](original-readbacks/20261119-0054/CHAIN_E8B_F0_READOUT.json)

旧 `3db79eb` 的原26个 CI runs 现已全部终态：15成功、11失败。实际205个 jobs 为156成功、41失败、7跳过、1取消；42份失败／取消日志均完整校验，API错误为0。collector壁钟6564.6504秒，子 CPU user42.8226秒、system10.4974秒；provider duration合计29408000ms与这些区间重叠，不能换算为 CPU 或钱。[旧26个完整终态原件](original-readbacks/20261119-0054/CHAIN_3DB_COMPLETE_TERMINAL_CI.json)

后续仍以原事务、原图校验和原 Host 检查为边界，定位同一次真实操作中的重复开销。首次 admission 全图校验发生在原 BEGIN 之前，其结论不会被带入后续 SQL 事务。

## 正在执行的下一步

1. 闭合 E6 启动组合的全部调用边界，冻结精确新源，再执行原组件与原 NoUpdate 父用例。
2. 继续 D 原 owner／issuer 路径与 source closure；先完成新 C，再进行真实冷恢复 D，保留 Adopt 的过期拒绝。
3. 补齐未来四题面板并冻结所有材料，然后实际运行两组更新后学生与原对照、记录恢复和 NoUpdate。
4. 对 Chain 后续最小候选做真实损坏图／取消／回调等价控制；只有取得实际收益才冻结下一原 F0。
5. 把每次失败、归档、自动 CI 和新增观测费用继续纳入原证据。人的认证、真实采用、来源授权和费用缺口保持真实状态。

所有活跃 owner、隔离 checkout 和 target 继续独占。不合并、不激活生产，不重放状态未知的请求，不把工程 journal 的 ADOPTED 转为 native owner、FinalUse 或结算资格。
