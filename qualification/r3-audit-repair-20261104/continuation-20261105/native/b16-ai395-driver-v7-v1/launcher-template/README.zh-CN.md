# B16 driver 启动器：禁用候选

本目录仅准备 foundation 之后的 `driver` epoch。实际 foundation 尚在原作业中运行，本候选没有填入预测终态，没有执行原生命令。`execute=false`、审批引用为空，源码、前序终态、metadata 与双锁的实际绑定仍为空。

## 最小变化

`launch_driver_v7.py` 从已批准的新 host foundation V7 V2 启动器派生。原有 10 个函数全文相同，包括工具、OpenSSL、libcap、V8 物理身份检查与最终清理阶段再次检查。29 个安装文件、25 项 runtime integrity、全部源码 payload、测试名单、物理断言、负控解析、零重试策略和 `negative_with_finally` 均未改。

新增 `verify_foundation_continuity` 只读实际前序证据，要求 foundation 为 `QUALIFIED`、无错误、最终源码守卫通过；其外层 launcher 和原 runner 均为退出码 0，SDK 最终检查无错误。前序启用的 binding、epoch terminal、launcher terminal 必须分别有真实路径及完整字节身份，且指向同一次运行。

driver 的初始 tree 必须等于实际 foundation 最终 tree。metadata 必须来自这同一 tree 上已经成功的原完整 `cargo metadata --format-version=1 --locked` 命令；保存原路径和 hash，另绑定该命令原 before/after whole-source guards。原普通 HEAD/index、两个锁以及实际工具、环境、SDK、缓存归属、helper 名单继续保持。原冻结 runner 会再校验完整依赖图和前序关系。

## 磁盘与执行范围

新启动目录为 `b16-driver-v7-ai395-20261105-v1`。安装和 subprocess 之前，实际可用空间必须至少 **48,517,479,536 B**：一族已观察产物 18,517,479,536 B，加 Cargo 12 GB、Bazel 8 GB、证据 2 GB、保留空间 8 GB。冻结 runtime 继续重新计算，并保持每命令前后的 8 GB 检查。这是规划门槛，不是峰值保证；没有缓存清理授权。

原 driver 顺序仍为 61 路径 adoption、真实 Cargo/Bazel 锁生成与检查、两组共 3 个因果负控、原 8 加新 4 共 12 个阳性控制、最后原 Bazel registration。ignored support 由父控制真实调用，不能算第 13 个阳性。pool、checkpoint、owning 均未获本候选授权。

## 交接

CI 可将实际证据填入其独立 disabled binding，再给 root 审核。本文目录中的 binding/request 是结构模板，不与 CI 的实际绑定争夺所有权。实际未来输入为空，故即使误改 `execute`，仍会在必要身份检查处拒绝。完整 934 KB request 仅供原生传输，不应加入产品证据目录；Git 审查对象保留小源文件、delta、模板和 manifest。

本次只做 Python AST 解析、原函数逐字对照、29 个压缩输入完整身份重算以及 25 项 integrity 对照。没有重新运行可选 guard 测试，也没有运行 native、Cargo 或 Bazel。

内部 `B11` 至 `B15` 是 `B16/phase` 的阶段编号，不是原 23 blocker 账本同名项；本交付不改变原 blocker 状态。
