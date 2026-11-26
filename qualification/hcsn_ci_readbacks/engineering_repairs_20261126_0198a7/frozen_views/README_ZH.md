# HCSN 冻结字节与首周期留存重算：实际发布记录

## 已完成的范围

2026-11-26，root 按一次注册执行完成隔离字节门与原首周期 verifier；两个阶段均 exit 0，没有自动重试。
总批次回执为 `PASS_BOUNDED_LOCAL_RESIDUALS`，首周期工程回执为 `RETAINED_CUSTODY_ARITHMETIC_PASS`。
原科学状态保持 **`HOLD_NO_GO`**；`whole_repository_qualified=false`。
本次关闭的是原证据来源与留存值重算阻塞，没有重新求解模型、生成参考解、训练或复跑 E1–E6。

## 来源与原字节

观测综合头：`eadf2999991c147759785f5eec722b9d6e796a9a`。
历史依赖头：`98335129e0ed61dcf07aef7ab59d8941f14643ab`。
证据头：`ce9ad88df0672df4d5c0bf7ba8d5c7e3c3fc0ce1`。
`ASSEMBLY.json` 明确记录混合来源；隔离视图不冒充任一 commit 的完整 checkout。
当前生产源、原冻结 manifest、原科学判据均未修改，生产源覆盖次数为 0。

| 已实际核验的项目 | 结果 |
|---|---|
| 注册输入 | ASSEMBLY、两份新封装、30 个 envelope，共 33 文件 |
| firstcycle 隔离视图 | 精确 22 文件，22/22 Git blob、20/20 原 SHA256 相符 |
| firstcycle 原输入 | 4 RAW.npz 与 4 SUMMARY.json，共 8/8 原输入 pin 相符 |
| Torch 隔离视图 | 10/10 原冻结源码 pin 相符；加原 manifest/archive 共 12 文件 |
| Torch baseline | 原 archive 与唯一 numpy001/ARRAYS.npz 成员的字节 SHA256 均相符 |
| 数值执行前后的身份 | firstcycle 22 文件及 INDEX，共 23 个前后 SHA256 完全相同 |

Torch 视图保留当前原清单要求的 `torch_flow.py` SHA256 `0f23d6ff6351be021f93d054b2cc2037ef76a87f29d11ca48fd4a725238bb5b4`。
当前原清单 SHA256 为 `afcc90fb68730219a60a94a48e28c9169a060858c8b11b9be623b7f496c76de6`。
没有退回旧 `2f735f48…` 版本，也没有把原 Torch native probe 执行资格转移到本次字节核对。
`INDEX.json` 的 false 仅描述本次字节阶段；第二阶段在独立 RESULT/stdout 中记录。冻结 TORCH-SOURCE 的原 INTENT 字段不是全生命周期账本，不能覆盖历史执行事实或重置已用额度。

## 原 verifier 的实际输出

运行环境为 Python **3.12.14**、NumPy **2.3.5**，Python optimization=0。
实际启动 1 个 verifier 子进程，保留 1 条 verifier-start 记录；读取 4 份原 NPZ archive。
原 stdout 明确记录 24 个查询行、192 条 quantity error rows、`read_only=true` 和 `status=HOLD_NO_GO`。
参考表仍为已留存的 12 个参考 case；原 verifier 同时重算有符号线性关系和首周期恒等式。
原 Decimal 精度 120、序列化容差 `1e-37 * max(abs(expected), 1e-300)`、相对诊断 floor `1e-12` 均未改变。
最后一条 stdout 为 `imports_checked`，被禁止的 qualification/Torch/SciPy/mpmath 模块列表为空。
子进程 stderr 为空、exit code=0、error=null。
本次字节/首周期核验的新模型、oracle、空间/DDE、训练及 optimizer 调用均为 0，且没有执行 Torch native probe；历史已有独立 probe，按 exact head/run 另行计账。

## 实际成本与计数口径

| root 外层记录的阶段 | wall 秒 | CPU 秒 |
|---|---:|---:|
| frozen-byte-materialization | 0.065407089 | 0.047061 |
| firstcycle-retained-readback | 0.165673162 | 0.148350 |

首周期封装内部另记 wall=0.124050073 秒、wrapper CPU=0.009936466 秒、child CPU=0.102326 秒、child peak RSS=23676 KiB。
这些内部成本已经属于外层阶段，不应再加到外层 CPU/wall 上重复计费。
注册的子进程上限为 CPU soft/hard 30/31 秒、地址空间 1 GiB、单文件 8 MiB，wall 45 秒；外层 wall 上限 60 秒。
所有实际值均在上限内；没有第二次调用已通过的 verifier。
同一总批次的 7 项 CPU gate 测试及 2 个 guard 子进程机械 PASS 原件完整保留，但该 gate 的适用范围随后被纠正。
该 gate 将完整 C2 replay 的预算合同用于独立 26-call 短 CPU 诊断，范围过宽，已经撤回、未发布；其机械 PASS 不能作为阻断短诊断的依据。
总回执中的 `source_gate_remains_hold` 是当时的机械观察；现行短 CPU 诊断应依其原独立 profile 评估，不能继承这个已撤回门禁。
原 7 项测试不计入本页数学重算分母，也不意味着未来 CI 的 35 次 adapter 检查已经执行。

## 原始回执身份

| 原件 | SHA256 |
|---|---|
| 注册 REGISTRATION.json | `4c2a5fcf45d9d5a4f0cf95929d7f0ad4b2651de327a393f4bcfa994d1a45434a` |
| 总批次 RESULT.json | `59968a7d0704012935fc053b6139e724add0ef9f6a463edd5b85994aa40a783e` |
| frozen_snapshot/INDEX.json | `64a757bcb598c1b3f08c3e4e48f03c92dec2e90e767d1f371ae10877bd4a5b19` |
| firstcycle_verifier/RESULT.json | `37a5187ffdc6806269e3b5276badd44dc536e68cffadee0ce715c99cfffc059d` |
| firstcycle_verifier/verifier.stdout | `7ad2bbad8c114abddf974ba6d5fdb04a241bf6dc192d064f48fe408ee798d68f` |

空 stderr 的 SHA256 为 `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855`。
独立审阅只读取上述现有原件、stdout/stderr、INDEX 与 before/after 表，并复核回执文件摘要；没有复跑程序。

## 归档保全与恢复

发布以外置 `FROZEN_VIEWS_READBACK_01.index.v2.json` 的实际归档/parts、字节数、SHA256 和原文件清单为准。
Git 正文仅保留两份新封装、本说明、首周期原 RESULT 的逐字节镜像与精简索引；原始大清单和重复源码由二进制归档保全。
归档须保全完整 33 个注册输入、原 REGISTRATION/ASSEMBLY、22/12 物化文件、INDEX、全部 stdout/stderr、实际 RESULT 及格式化/执行回执。
若索引列出 `orderedparts`，先逐项核对 part 的字节数和 SHA256，再严格按登记顺序连接；不猜测顺序，也不对 part 单独解压。
取得完整 archive 后核对整体字节数/SHA256，再检查成员只落在预期相对路径，解包到全新空目录，逐项核对原文件清单哈希。
然后只读对应的 `frozen_snapshot/INDEX.json`、`firstcycle_verifier/RESULT.json`、原 stdout/stderr 与注册清单即可复核本次结果。
已有物化原件，无需再运行 materializer、verifier、audit.py、analytic_reference.py 或任何原工作流；恢复运输不创造新的运行额度。
归档内绝对路径属于原执行环境的来源记录，应原样保留，不为本地重定位改写旧回执。

## 仍开放的资格

首周期原科学 HOLD、稀有量精度、长时间延迟再生、完整边界/物理参数训练与连续时间重采样不变性均未因此通过。
历史 [#6248 原成功 run43217764472](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/43217764472/job/131181247635) 与 [#7000 后继双 lane run45106995789](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/45106995789) 均有独立原件；本次不重放、不转移其资格，固定物理一阶振幅范围也不扩展为完整网络训练。
本次 frozen views 保全不新增 CI、不 dispatch/重试历史 CI、不改变冻结训练预算；整仓资格继续 HOLD。
本说明仅更正未发布说明的范围：CPU gate 已撤回；本次零模型调用不代表历史从未执行。主归档、旧 FINAL README、旧外置 index、执行日志和 RESULT 均保留原字节。

