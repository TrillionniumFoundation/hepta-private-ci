# 本地闭合：真实 FP64 Head、完整 Adam 续训与 pandas 源码 pilot

本轮从 `56b5815a8ae811f6846e92dbbe46ca1a74d83f2f` 继续，未查询或等待远端 CI。
真实实验的共同冻结代码为 `3257b035e5dc3c381e1a2342ba69d55a0a35293b`；
归档与报告工具冻结于 `92bc5d9913eb60316a9620e677e47e21ee96d19d`。
所有旧学习质量结果保持原义。本轮验证系统实现、状态恢复和新项目执行路径，
没有新增 Encoder 调用、校准拟合、独立 holdout 或任务质量晋级。

## 结论

| 本轮工程缺口 | 实际闭合证据 |
|---|---|
| 真实训练参数未接入原生 Head | 27 个原 FP64 状态、64 行输入、3,456 个 logits 全量对照通过；最大绝对误差 `3.1086244689504383e-15`，argmax 全部一致 |
| 只有最终参数，缺少完整续训能力 | 24 个新进程、3,060 次私有更新；新 controller 的不中断与续训路径完整状态逐位相同，且三模式与旧训练器的参数及损失误差均为零 |
| 新的带原生扩展项目不能可靠执行 | pandas 两个真实 revision、历史依赖环境、完整来源和原测试实际执行；8 次 benchmark 完成，最终来源/环境核验通过 |
| 证据依赖当前进程或展开目录 | 完整数据包恢复了 608 个独立文件；从恢复后的 artifact 再次执行 native，并在三个新进程读取完整 optimizer 终态，新增优化更新为零 |

**学习质量仍未获得新的通过结论。** pandas 主动作含 skip/xfail，标签按冻结规则保持
`null`；本 pilot 得到 3 个有效负例、0 个有效正例。n128、跨任务泛化、门控优于线性、
多模态学习增益与“最优干细胞”选择，均不能由这些工程验收推出。

## 1. 原生接口保持真实参数和共享所有权

原 Q24 `SharedEncoderOwnerV1` / `CellHeadV1` 契约保留。新增的
`SharedLearnedFeatures770V1` / `LearnedCellHead770V1` 是平行的固定研究 profile：
770 维、2 类、rank4，支持 linear、逐特征 gated、gated + tanh residual。
导入完整 FP64 参数，不转换为 Q24 或 float32。

特征导入检查完整 artifact、feature identity、generation、来源 digest 顺序和 1–64 行上限；
归一化只做一次，所有 Head 借用同一不可变缓冲区。Head 还核验 task、原 predictor digest、
每个参数名称、shape、dtype 和原始字节。拒绝错误身份、损坏/超界输入及非有限中间值。
Cell registry 负责将 immutable predictor 分配给 Cell；此接口本身不创建 Cell 身份或训练器。

| 模式 | 每 Head FP64 参数字节 | 参数与两份 Adam moments 的纯张量字节 | 原生最大 logit 误差 |
|---|---:|---:|---:|
| Linear | 12,336 | 37,008 | `3.1086244689504383e-15` |
| Gated | 24,656 | 73,968 | `2.886579864025407e-15` |
| Residual | 73,936 | 221,808 | `2.4424906541753444e-15` |

这些不是进程 RSS 或全部训练成本：尚有输入、梯度、临时工作区、索引、来源、序列化和对象开销。
64 行共享归一化特征为 394,240 B；此次 27 个记录状态的参数总量为 998,352 B。
example 顺序导入/执行 Head，峰值单个 Head 参数 payload 为 73,936 B。

测试输入沿用旧 770D bundle 的 64 行和 27 个状态。它们来自同一历史 action-usefulness
任务的三模式、三预算、三种子，不能解释为 27 项新能力。原生程序没有收到 NumPy reference；
reference 只由父进程用于比较。预设绝对容差始终为 `1e-9`，没有事后放宽。

输出明确为 raw logits、未校准、`ShadowOnly`、`DENY_ALL`、quality false。
没有接受 mask、动作执行或晋级入口。Rust 对非有限中间值的拒绝比允许 clip/tanh 隐藏溢出的
NumPy 极端输入路径更严格；不声称所有有限极端参数普遍等价，也不声称跨语言逐位浮点相同。
本次 native 使用开发构建；它验证数值接入，不提供新的吞吐量优势结论。

## 2. 完整 Adam 状态可以在新进程继续

使用原冻结 TRAIN bank：32 行、32 个不同 bug groups、每类 16 行。每模式 17 个
独立初始化的 Cell，seed 为 `1000000+i`，20 步，microbatch8，分块 `8+8+1`。
每种模式各跑不中断、六段新进程续训、旧 MicrobatchCellTrainer 三条路径。

| 固定暂停游标 | 3 | 20 | 27 | 40 | 59 | 60 |
|---|---:|---:|---:|---:|---:|---:|
| 该段每模式新增私有更新 | 24 | 136 | 56 | 104 | 19 | 1 |

三模式合计 24 workers、3,060 次参数更新、97,920 次 example updates。真实实验一次通过，
没有失败后换初始化或重跑训练。全部 Cell 的最终步数均为 20。

完整 checkpoint 包含参数、m/v、step/cursor、raw/normalized bank、行索引、labels、
来源 ID 和记录 digest、Cell/task 顺序、feature identity、generation、初始参数 digest、
优化器配置、代码/NumPy 身份和 trajectory hash。此训练是固定 full-batch 顺序，没有随机
minibatch sampler，不编造不存在的 RNG 状态。

不中断与续训比较包含 shape/dtype/原始字节的摘要，区分 `+0.0` 与 `-0.0`；
parameters、moments、steps、loss、trajectory 均逐位相同。三模式对旧训练器的最大参数、
初始损失、最终损失误差全部为 `0.0`，固定验收门仍为 `atol=rtol=1e-10`。

保存前检查可恢复预算；加载前检查 NPZ/NPY 头、数量、shape、dtype、总展开字节和外部
manifest/plan/input pins。未访问 Cell 必须符合原初始化 digest。半步更新中的
KeyboardInterrupt/SystemExit 使 owner 失效，不能保存成完整状态或继续更新。
这是完成更新边界上的同步 checkpoint，没有承诺掉电原子性或强制 kill 后恢复半步工作。

主运行产物共 96 个文件、41,078,369 B。其中 21 个 checkpoint NPZ 共 38,823,984 B，
保存的未压缩张量合计 47,988,528 B。整个真实对照的外层 wall 为 8.229658304 s，
已知 CPU 为 7.699561742 s；reaped-child lifetime peak 为 55,390,208 B，不能加总成全系统峰值。
从完整归档恢复后又执行了三个独立 `--kind verify` 进程，更新数均为零。

## 3. pandas 的真实执行与负面结果

bug5 在观察测试前因唯一完整 40 位 base SHA 被选为 TRAIN/build pilot。
base 为 `4f4282f8a7c1033fc3efe9f4eab5368a70ae5041`，candidate 为
`0babe10f1f3f19bb6183b6fb4cc958583c6860c8`。metadata 的 `bug_patch.txt` 与实际 commit
diff 不一致；保留冲突，实际比较使用锁定 Git revision 和原测试。

使用 CPython3.8.20、NumPy1.18.4、Cython0.29.19、pytest5.4.3 及完整 hash lock。
上游声明 Python3.8.3，此差异公开保留；这不是原始系统镜像的完整复现。

构建历史为两次启动：base 完整成功；candidate 在剩余磁盘低于原 1 GB reserve 时中断。
失败日志和 CPU 已保留。candidate 已生成的 38 个扩展与 base 逐字节相同；
1,964 个其余原始/生成源码文件（含 139 个 native inputs）、compiler/ABI/runtime/flags
的等价证明支持复用缺失的 3 个扩展，共 574,032 B。之后 fresh import 核验全部 41 个扩展
来自 candidate checkout。没有第三次编译，也不能称为两次完整独立成功构建。

原测试和三个同文件对照在观察 outcome 前已经封存。每次构造完整、可核验的 fresh workspace，
使用同一 candidate 测试 overlay、对应 revision 的 qualified native artifacts；不调用会
删除 `.so` 的旧 clean runner。8 次测试都实际启动，结束后复核来源和环境。

| 冻结动作 | Base | Candidate | 最终标签 |
|---|---|---|---|
| `test_ops_not_as_index`，primary | 13 普通通过、2 AssertionError；6 xfail、3 skip | 15 普通通过；6 xfail、3 skip | `null` |
| `test_median_empty_bins` | 3 通过 | 相同 3 通过 | 0 |
| `test_non_cython_api` | 1 通过 | 相同 1 通过 | 0 |
| `test_frame_describe_tupleindex` | 1 通过 | 相同 1 通过 | 0 |

primary 的失败明确是 sem/std 两个普通断言。虽然 candidate 修复了它们，整条 action 含有
skip/xfail，必须服从冻结的 unknown 规则。没有事后选取失败参数或把 null 改为正例。
所得是 1 个 TRAIN bug group、3 个有效负例、1 个 unknown，未形成新的正负平衡学习队列。
最终 verifier 通过 99 项检查和 6,446 条文件记录；没有重跑原始 benchmark。

## 4. 完整成本与验收范围

| 不重复的计价范围 | Work wall / s | 已知 CPU / s |
|---|---:|---:|
| Native export 外层 | 0.353563 | 0.305995 |
| Native parity 外层 | 0.358921 | 0.317815 |
| 24-worker optimizer 对照外层 | 8.229658 | 7.699562 |
| Pandas 21 个准备、依赖、编译命令，含失败 | 612.446045 | 643.429727 |
| Candidate artifact recovery，含 import | 2.656402 | 2.548846 |
| 8 次 pandas benchmark 的完整执行段 | 22.830981 | 22.809981 |

表中 wall 是工作区间，不是可加总的会话经过时间。详细账本逐项绑定原收据，排除嵌套 worker、
observer、recovered import 的重复计价；还单列本地测试、源码 materialization、缓存恢复、
Git 保存、归档/恢复、最终 fix/fmt。被中断编译的额外后代 CPU、API CPU、未计量编辑/启动、
历史缓存获取和整个共享系统峰值均保留 unknown，不补成零。

真实 neuron crate 的 `just test -p codex-hepta-neuron --locked` 为 109/109，通过的
范围包含 9 个新 native 测试。Python 的 exporter/probe、optimizer、pandas 组件分别有
7、22、10 个针对性测试定义和原始执行收据。初期缺失共享 Cargo cache、一次错误构建 cwd、
磁盘 guard 和恢复 Git 空目录的问题均保留失败记录；最后使用本任务独立 Cargo cache。

## 5. 证据与后续边界

完整数据包为 `hepta-cell-native-resume-pandas-evidence-v1.tar.gz`，55,762,229 B，
SHA256 `3ac97d19ac129517e49df6ff880de6df6126193fe92a81b80f14a76690a1413e`。
外部 index 为 59,440 B，SHA256
`6ce025c85a10060fc57b9c103773adcb323f37025847b6f575d4cdf2689dbb8a`。
608 个逻辑文件、507 个内容对象已经完整恢复并逐文件核验；所有文件都是独立普通文件。
原生重放最大误差与首次相同，三个完整 optimizer 终态通过新进程零更新验证。
恢复的 pandas Git tree、关键原测试/source blobs 和两角色的 82 个 extension 绑定也核验通过。

归档保留实测 binary、原 Head/输入、完整 optimizer checkpoints、成功与失败日志、来源
Git objects、qualified extensions 和版本/依赖清单。Hepta 源码与历史执行快照保存在 Git。
archive 自身的生成、恢复及最后格式化收据位于后续 closing/terminal 记录，避免自引用。
复现步骤见 [REPRODUCE.md](REPRODUCE.md)；机器可读结论及最后状态见
`facts.json`、`terminal-evidence.json`、`delivery-index.json`。

本轮使共享特征上的真实小 Head 可以原生执行、完整保存并继续学习；它没有证明门控必然比
线性更强。当前投入仍应围绕真实任务数据、线性/门控公平对照和可恢复的小 Head 训练。
新的前瞻数据批次必须重新冻结未观察的来源与评分规则；本 pilot 和旧 holdout 的已观察结果
不能改称新的确认集，也不能用更多 Cell 数量代替更多已学会的任务。
