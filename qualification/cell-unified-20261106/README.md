# Cell 统一候选：真实学习、历史权重与现有 owner

本候选把 #4929 的 V2 generation owner、#4890 的角色／人口与分化研究接口、
#4930 的 V13 完整训练状态验证放进同一棵源码树，并增加从真实 V1/V2 journal
读取的 inventory。验收结论按具体证据范围给出；工程路径通过不授予能力收益、
正向采用、完整成本或 RSI 资格。

**固定原生门通过：984 tests run、984 passed、67 skipped，0 次失败重试。**
测试 commit 为 `6a938bea7ba0fc3dd234930c765729c1a9172a65`，tree 为
`bf3c2501b0d9ad370cf035481a07cb5a2bf1a3c4`。严格 Clippy、同源 helper、最终
`just fix`／`just fmt` 均退出 0，最终源码未变，fix／fmt 后未重跑测试。
后续提交增加研究证据和说明，Rust source subtree 与已验收版本精确相同。
参见 [RESULTS](RESULTS.json)、[全部跳过项及实际测试清单](COVERAGE.json)、
[原始回执与完整归档](evidence/native-final/BUNDLE.json)。大于单 blob 上限的
原 control journal／compiler log 保留在可验证的完整归档内，没有截断。

## 本轮固定的边界

| 层次 | 本轮实际工作 | 仍不能推出的结论 |
|---|---|---|
| P0 | 合并明确的 donor；现有 journal 的有边界、带身份及状态栅栏的只读观察；同源码原生门 | 角色标签已成为生产 artifact 契约、所有研究后端已注册普通产品入口、全 workspace 通过 |
| P1 | 一次真实 16-update Memory 候选；完整状态、独立进程评价／冷加载／下一任务；真实 SourceOwner 拒绝与来源失效 | 有收益候选已正向采用、真实未来任务净收益、历史错误知识已被纠正 |
| P2 | 恢复历史 Joint 后代；真实 Cargo helper 数值对照；普通 Agentd 生命周期及 admission-cancel | 原父权重已恢复、自然任务质量改善、optimizer 可恢复、全成本闭合 |
| P3 | 保留既有分化研究和采用门，记录本次保留能力退步 | 已超过固定专家等强基线 |
| P4 | 保留 lineage／完整恢复状态与长期对照要求 | 后代改善了后续改进效率 |
| P5 | 使用现有 bounded service、journal、outbox 与恢复路径 | 扩大活跃 Cell 带来净收益，或已经给出规模／p99 曲线 |

## 来源与 owner

基座是 #4929 `7391c3dc3b0a496b62be4c6cf2769d2ae0c9db75`；整合了
#4890 `caf06e0d9c78ba2b8e2ab860ec1b37f049e30f1b` 与
#4930 `dd1adf3defc5f1b1bcf3358419e23490e24b9a6a`，保留真实 merge parents。
发布使用 Git 数据接口；本地与远端 commit header 可不同，tree 内容逐次精确核对。

`CellOwnerInventoryV1` 只能从现有健康 journal 取得。活 view 借用 owner，
脱离 owner 的 record 不能重新参与 census。栅栏包含实际 journal checkpoint，
因此取消、drain 和 ACK 即使不改变状态 revision，也会使旧观察失效。census
拒绝跨 principal／agent／run、重复逻辑 Cell 槽位、V1/V2 同槽重复和溢出，
单次最多 4096 个观察。没有新增写 owner、训练 authority 或 journal 格式。

这些数值是选定 owner 槽位、backend binding、parameter bundle、pending／outbox
和逻辑字节预算。它们不等于角色能力种类、专家版本、正在用 CPU 的 Cell 数量、
OS RSS 或完整成本；也不证明发现了系统中所有 owner。原角色／人口 API 与
这些事实观察保持语义区别，role membership 的真实 artifact 契约仍未接完。

## P1：有真实学习，也有实测退步

完整记录见 [Memory 交付](../cell-learning-loop-v1/README.md)、
[RESULTS](../cell-learning-loop-v1/RESULTS.json) 和
[原发布门审计](../cell-learning-loop-v1/GATE_AUDIT.json)。

一次固定训练将原 step240 完整状态推进到 step256：124 条训练行，16 次
optimizer update、288 次实际样本呈现。真实 MiniLM 重编码原 120 条特征的
最大绝对差为 0；父、候选及历史冷恢复均通过默认 reference／non-synthetic
内容闭包验证，验证回执的 authority 仍为 DENY_ALL。

两个冻结 Cedar 工程请求为父 0/2、候选 2/2；历史 72 个 typed-output 任务为
父 59/72、候选 55/72，即五项退步、一项进步。新进程加载候选后的下一任务
确实执行 sort_numeric；这是未发布 shadow 使用。拒绝发布后，父 epoch 保持 1，
另一新进程使用父版本完成下一任务。最终 skills 来源修订使父 release 失效，
冷读取正确拒绝服务，历史父字节及参数、Adam、RNG、sampler 全状态仍完整。

原运行的发布 callback 在训练前即固定为拒绝：缺少独立九臂 future round，
完整成本未知。59→55 不是该 callback 动态判定的触发原因。它验证了真实
拒绝／留父路径；有收益新候选的正向采用仍未验证。后验的动态质量重放另存
在独立目录，不能追认为原预注册运行，也不能授予 formal adoption authority。

[后验动态重放](../cell-learning-loop-v1/decision_replay/README.md) 另行冻结，
重新用真实 encoder 和两个 head 执行全部 74 例，严格核对原 typed outputs、
checkpoint、state 和 case roster。动态谓词要求纠正任务严格改善且历史总正确数
不下降；实测结果产生 `historical_retention_loss`。真实 fork SourceOwner
callback 执行并拒绝，冷进程父版本仍正确工作。formal／cost 仍分别 HOLD，
原 owner 保持原 fence，没有回退或重新授权。新增 CPU 3.099507 s、wall
3.140813905 s、0 optimizer updates；四个身份／伪分数／类型负例全部拒绝。

Cedar 是人工编写的工程任务；父从未学习过旧 Cedar 标签。最终 skills 修订
只改变来源版本，没有改变标签。两者均不构成自然未来流量或已经学会的错误
知识被纠正的证据。

两次完整 driver 调用的 Linux wait4 计量为 CPU 7.730896 s、wall 合计
7.792046205 s、峰值 RSS 212811776 bytes，覆盖解释器启动、准备、10 个独立
worker instance 和最终落盘。能耗、历史获取、完整 byte-seconds、网络、账单、
p99、开发审阅等仍未知或明确排除，不能把该数字当全生命周期总成本。

## P2：历史训练资产回到真实执行路径

完整来源和覆盖范围见 [Joint 回收说明](../joint-trained-recovery-v1/README.zh.md)。
回收的是原 `9032b075…` 的历史训练后代 `33c1aa75…`，不是缺失父模型的替身。
固定归档和全部 67 个张量经过校验，596985 参数完整，0 次新训练更新。

唯一一轮 39 个真实 Cargo helper 新进程全部 exit0。完整恢复状态的最大误差：
FP64 `7.771561172376096e-16`，FP32 `1.8493976472466755e-07`；预定阈值分别
为 `1e-9` 和 `5e-5`。逐模态 mean 输出、Stop flush 字节和 Auto 后继行为一致。
actor／critic／emission-head 原始浮点向量不在当前 ABI 内，未作同等误差声明。

普通 Agentd 测试分别检查历史权重的输出、ACK、outbox 恢复、相同请求读回，
以及真实 Init 后的 admission-cancel／取消结果冷恢复。取消测试不保证 Shared
子进程已启动，也不覆盖正在发布媒体时的强制中断。数值门不能替代此原生门。

30 条 owner ledger 并非完整当前 wall：后续 collect／settle、journal fsync／
witness、ACK 持久化、服务重开、资产加载等仍有未完整覆盖的阶段。历史自由文本
评价 state／zero-state／shuffled-state 均 0/4；本轮数值一致性不改变这一结果。

## 失败、验收和下一步准入条件

原 #4929 固定源码的旧原生结果是 6631 tests run、6577 passed、51 failed、
3 timed out、94 skipped，不能移植为本候选的 PASS。原始摘要保留在
[donor-7391c3d](evidence/donor-7391c3d/scoped-runner-summary.json)。本轮修复了
POSIX shell 丢弃含连字符 helper 环境变量名的问题，两种名字均绑定同一真实
Cargo compiler artifact，没有猜测 target 路径或缺资产跳过。

本轮第一次 launcher 因继承的 sparse checkout 缺少新 gate 文件退出 2，
尚未执行任何原生验收；第二次严格 Clippy 在两处导入的 redundant clone 退出
101，测试未启动。两项失败均保留；修复只作用于本轮独立 checkout。后续原生门
固定五个相关 package，要求干净 source、相同 compiler helper、fresh JUnit、
无测试失败且退出 0。不修改 sandbox 标志，不控制其他任务的 Rust 进程。

下一阶段应先用真实来源任务验证动态采用及保留，不增加训练步数来掩盖当前
退步。P3 必须完成强基线、独立未来来源及完整成本；P4 必须有固定方法长期对照
和可重复未来收益；P5 必须报告活跃数增加的净收益、尾延迟、容量回收和恢复曲线。
在这些证据出现前，分化／进化／规模收益的结论保持 HOLD。
