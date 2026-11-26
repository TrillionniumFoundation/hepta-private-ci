# Torch 历史 probe 回读与当前准入差异

## 本次结论与范围

原小型 Torch probe 已真实执行并成功；本次恢复冻结字节没有产生可重用的“尚未执行机会”。
历史 probe 缺少可定位回执这一项，可由本包的原日志、RESULT、来源清单和 Actions 元数据闭合。
当前集成头的整个 runtime 资格不因此转移；既有 source admission 差异仍须按具体来源评审。

本次只读 GitHub、对文本和 JSON 做静态比较、哈希与归档；新增模型、adjoint、backward、optimizer、测试执行均为 0。
这些 0 只描述本次回读，不表示整个 HCSN 研究从未运行模型。既有运行逐个按 exact head / run / job 记账。
原单次上限 220 forward / 32 adjoint 是单次上限，不是成功后余下 54 / 22 次的可再执行额度。

## 已发生的五项独立执行

成功行的计数顺序均为 forward / adjoint / backward attempt / guard rejection / optimizer。

| 既有执行 | 精确来源与定位 | 原结果 |
|---|---|---|
| red001 | `bc1b94039dea52c5426b99ba617f7a2f59742377`；run43216185145 / job131175904511 | HOLD；1 forward、0 adjoint/backward/optimizer；写只读 `ctx.metadata` 失败 |
| green002 | `975a169df5f3a1dd51b81ddd51b0a338592a0e0f`；run43217764472 / job131181247635 | PASS；166 / 10 / 32 / 20 / 0 |
| 后继 archived | run45106995789 / job137470458710；检出上述 `975a169…` | PASS；另一次 166 / 10 / 32 / 20 / 0 |
| 后继 current | `7869063345ea43cc9cb83ff6d76d70bf94ff62a5`；同 run / job137470458296 | PASS；另一次 166 / 10 / 32 / 20 / 0 |
| 独立 current | 同一 `7869063…`；原 RESULT blob `57385a0d7ff446fde81e659154ef97ff36961e20` | PASS；另一次 166 / 10 / 32 / 20 / 0 |

原 red/green 使用 Torch2.8.0+cpu，两个后继 hosted lane 使用 Torch2.10.0+cpu，独立 current 使用 Torch2.15.0+cpu。
原及 hosted Python 为3.12.16，独立 current 为3.12.14；NumPy2.3.5 / SciPy1.17.0，原成功记录均单线程。
32 次 backward attempt 包含原 guard 和 undefined-gradient 路径，不能全部算成真实 adjoint。
此表是本次核到的五项执行，不能当作全研究生命周期的完整执行账本。

| 既有执行 | 完整子过程 wall / CPU 秒 | 峰值 RSS KiB |
|---|---:|---:|
| red001 | 2.330044445 / 2.185178 | 344044 |
| green002 | 60.759934334 / 60.306657 | 454140 |
| 后继 archived | 56.723528189 / 56.285226 | 498460 |
| 后继 current | 65.028662539 / 64.542695 | 431404 |
| 独立 current | 70.259465112 / 69.582394 | 319008 |

上表均为既有完整过程成本；本次没有重新产生这些成本，也没有再加内部 validation 时间。
既有 archived/current 数组比较记录为888数组、38805值，714数组逐位相同，最大绝对差4.829470157119431e-11。
独立 current 与 hosted current 的原 ARRAYS SHA 相同；本次只读原比较报告及摘要，没有重载 NPZ 或重算数值。
原 SciPy BDF invalid-subtraction warning 仍在完整日志中，不能据 PASS 声称其已被证明无害。

## 当前 11 源矩阵与已有修复

观测集成头为 `55ffa46dc4a74e01714b13bb3625f9ca12aeb684`，对照已成功的 `7869063…`。
按原 CURRENT-SOURCE 的11路径读取 Git 对象，9/11完全同 blob；完整矩阵在归档 `CURRENT_11_BLOB_COMPARISON.json`。
共同9项是 REQUEST、torch_flow、refractory、spatial、graded model/spatial、initial adjoint solver、joint model、state_io。

| 不同项 | 当前 Git blob | 已成功后继 Git blob |
|---|---|---|
| workflow | `9d908458d859bbe0fcf95d2c3c078a2c5139246d` | `5c95211cfd90f4c62a8d837a39b3c586a0ae8726` |
| native_probe | `5fcce67fe9ca342c8d4f735e438f5300299ee953` | `887782b2f4fd1e1fae2b2baa5d4a11dc9c0b9e20` |

当前 workflow 第40–44行仍取旧10源 TORCH-SOURCE 准入；原清单是历史身份，不能为适配新树而刷新。
已成功 #7000 的 native_probe 第65–69、78–79行仅添加 current-source 参数与清单选择；两处文本变换后全文等同，原数值判据不变。
其 workflow 第51–61行明确把 state_io 加为第11源，第72–74行给 current lane 传参数；第18–23行是已经执行过的双 lane。
`torch_flow.py` 的保留属性碰撞已在旧成功版本用 `ctx._hcsn_metadata` 修复，当前也是同一 blob。

[既有独立修复 #7000](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/7000) 已可评审，分支为 `research/hcsn-current-adjoint-requalification-20261123`。
直接查看其固定 [workflow](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/7869063345ea43cc9cb83ff6d76d70bf94ff62a5/.github/workflows/hcsn-continuous-adjoint-torch.yml)、[native_probe](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/7869063345ea43cc9cb83ff6d76d70bf94ff62a5/qualification/hcsn_adjoint_torch/native_probe.py) 和 [CURRENT-SOURCE](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/7869063345ea43cc9cb83ff6d76d70bf94ff62a5/qualification/hcsn_adjoint_torch/CURRENT-SOURCE.json)。
[既有集成草案 #7005](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/7005) 也已引用该修复；本次观测其 head 为 `de4ef594bfefec05a64fc2ae3b717a640a57b263`，不签收整头。
本次以固定链接承接源码和原结果，不复制修复代码、不创建或更新会重新触发这两个166-forward lane的 PR。
两个已读 workflow 的触发器均为指定源码路径的 pull_request；本证据子目录不命中它们，不代表其它 CI 不会运行。

## 原件、恢复与仍未获得的资格

- [原失败日志](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/43216185145/job/131175904511)及[原成功日志](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/43217764472/job/131181247635)逐项保存在本包 envelope。
- [原成功持久原件](https://github.com/TrillionniumFoundation/hepta-private-ci/tree/2147dd4e9c844180657b7dfce33a3b827353f82a/qualification/hcsn_ci_readbacks/6248-green002)和[后继持久原件](https://github.com/TrillionniumFoundation/hepta-private-ci/tree/f5dbb9861674c85ac9711ade9a6f154a8201d6c7/qualification/hcsn_ci_readbacks/current-adjoint-7869063)保留原 ZIP/数组；本小包没有再复制这些大二进制。
- 外置 `TORCH_HISTORY_READBACK_01.index.json` 给出本小包的字节数、SHA和完整成员清单位置；先核 SHA，再解 tar.xz。
- 内部清单逐项绑定22个 GitHub readback envelope、矩阵、指针、静态评审和说明；Git文件 content 的 Git blob 标识另做字节重算。
- 原 job log 以工具返回的完整解码字符串存于 JSON；不把这种文本封存冒称 Actions 原 ZIP 传输字节。
- 此包完全独立于已封存 FROZEN_VIEWS_READBACK_01；不重打包、不覆盖该包及任何旧 README/index。

原冻结 INTENT/new_torch_executions=0 是运行前注册身份，不能覆盖其后已有成功回执。
成功范围仅是固定 N7/N12 小模型、固定物理/支撑的一阶输入伴随；没有证明自由边界/物理参数梯度、高阶梯度、N512、全网络训练或该 probe 的 Adam 恢复资格。
当前 head 的 harness/runtime 身份与整个 HCSN 研究仍分别保留未闭合范围；本次只闭合“历史 probe 回执缺失”。
