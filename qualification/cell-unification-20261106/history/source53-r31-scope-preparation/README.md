# Source53：真实 R31 metadata 派生的最终整理范围

这里是纯本地范围准备，**不是 R31 工作区通过结论，也不授权执行 fix 或 fmt**。四份输入绑定 source53 commit `f74be175de66a4b351cd239d39d98cd34fe9cc1b`、tree `440d4a8e09af4009e4d9ea067388826308da8803`，供已冻结的 source53 finalizer 后续核对。

## 实际输入与字节来源

R31 的实际 job 为 `1a1b275ba33-fc05-7e17`。其原始 `cargo metadata --locked --no-deps --format-version 1` 已自然返回 0，耗时约 0.154784 秒；原 raw result、receipt、源码前后守卫、file_info、launch 与根授权均按原字节保存。守卫确认 197 条源码、原 HEAD `bef6fa7645df9df12b69fda499e97eed25de6c75` 及双锁。

该次 metadata 原始 stdout 为 937,659 字节，SHA256 `b29d6b0c49c63d6345f50597873e3fa98c79ea0cbfe923ae3dd700b5cc08af8d`，与本地已保全的 R29 metadata 字节完全相同。这里复用的是同哈希的传输字节，并用 **R31 新调用** 的原 raw、receipt、file_info 重新绑定来源；没有把 R29 的执行改称 R31。metadata 以 mtime=0 的无损 gzip 保存。

R31 的 scope 原件独立通过两个固定 version 的 binary_read 分块读回，逐块、完整 SHA256、长度及原始成员顺序均核验。`TRANSFER-READBACK.json` 和 `INPUT-SOURCE-MAPPING.json` 保留这种区别。原 R31 启动读回中当时的 pending 字段原样保存，不重写历史快照。

## 四份输入

| 文件 | 内容 |
| --- | --- |
| `EXPECTED-SELECTION.json` | 197 条 changed path；默认格式化选中 183 个 Rust 文件和 2 个 Python 文件；193 个实际成员及默认成员；26 个 Rust owner 和 27 个 CI selector。 |
| `PACKAGE-ARGS.json` | 26 个真实 owner 的原 `just fix --locked -p …` 命令；原 recipe 的 `cargo clippy --fix --tests --allow-dirty` 保留，没有额外 `--allow-staged`。 |
| `RUST-FILE-COMMANDS.json` | 对每个 Rust 文件按实际 metadata 的最近 Cargo manifest 父目录，生成原 rustfmt cwd、edition 2024 与 `imports_granularity=Item,skip_children=true` 参数。 |
| `PRIMARY-SOURCE-PINS.json` | 原 34 个格式化与依赖上下文输入的 **13,098 字节原文完全不变**；SHA256 `afc57e362890925d5628947a95dd1f719816996d0b26b2fef101dbcf827e7dd3`。 |

27 个 CI selector 比 26 个 fix owner 多出的仅是 `codex-hepta-control-plane`。它不扩张 fix 范围。两个 Python 输入为 `scripts/run-nextest.py` 与 `scripts/test_run_nextest_helpers.py`，原命令为 `uv run --frozen --project scripts ruff format` 加这两个路径。其他 12 条 changed path 不在默认格式化选择中。

原 `format.py` 使用 HEAD 差异与未跟踪文件选择；这里静态推导其预期范围，没有执行 Git selector 或 formatter。最终运行仍须核原 HEAD、实时路径集合及 34 个上下文文件，不能改成 `--all`。原 primary pins 保留历史固定源码链接；新添加的两个 Bedrock Rust leaf 不改变这些上下文文件。源码 manifest 自身的历史准备态字段按原字节保留，当前实际调用证据另列。

## 可复算材料与权限边界

`prepare_closed_inputs.py` 仅复制已经闭合的原件、重组 scope 传输分块并压缩相同 metadata 字节。`generate_scope_template.py` 保留 `FROZEN=False` 和空绑定；独立的 `generate_scope_bound.py` 只绑定这批闭合输入并执行纯本地派生。精确差分、逆变换和实际本地返回码均保留。`verify_output_contract.py` 以另一种父目录遍历重算 183 个文件命令，并静态核已冻结 finalizer 所消费的字段；没有 import 或运行 finalizer。

当前不提供 R31 终态或测试通过资格。真正执行 finalizer 仍须取得同源 R31 完整 PASS、R30 原完整 PASS、实际新工具 inventory、源码与锁守卫及根明确授权。source52 R28 的历史通过与 R29/R26/R24 的历史失败保持各自身份。没有执行任何 native、Rust、Cargo metadata、fix、fmt 或新测试，没有修改既有冻结文件、主报告、INDEX 或 ledger。
