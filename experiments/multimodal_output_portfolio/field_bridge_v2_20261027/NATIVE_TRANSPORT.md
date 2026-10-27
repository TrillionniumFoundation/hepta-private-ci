# V2 原生传输与成本检查

## 结论和范围

新增进程内 C ABI 调用**原来的 `sparse_tick`**，不改变神经元动力学、归一化、两轮输入、读出状态或权限。原始源提交仍是 `63f198ad85cfa2aa579032256355f446cfe793a0`。保留 V1 JSON 进程桥用于独立逐项比较；V1 科学代码和结果没有改动。

本次闭合的是“可以在保留原生状态与可重放记录的同时，减少进程桥接开销”这个工程问题。24 个随机顺序配对测量块中，完整记录路径的中位耗时从每例 207.92 μs 降到 101.96 μs；逐块比值的中位数为 1.93 倍。双方均不写完整记录时，从 169.84 μs 降到 40.67 μs，逐块比值中位数为 4.14 倍。

这不确立 Hepta 的复杂度优势。同一 40 维、五动作读出工作量下，简单历史特征路径的中位耗时为每例 1.40 μs。紧凑原生路径与历史的逐块耗时比中位数仍为 29.49。只有在新的效用实验中验证的质量、动作成本或其他收益，才能为这部分开销提供依据。

## 实现

`native_ffi.rs` 仅构造 V1 同一个固定 `SparseConfig`、两个 `SparseTick` 和完整回执。固定常量使用只读缓存；每例的状态独立。新 ABI 传递固定大小结构：输入 432 字节、输出 1,816 字节。原始 83 个 crate 源文件保持不变。`build_native_fast.py` 核验原始源码、精确 Rust 1.90.0 编译器与 33 个编译器/标准库身份，记录所链接 rlib 的哈希及生成库身份。

随后在新的空目标目录，以精确缓存依赖执行了一次 `cargo build --offline --locked --release -p codex-hepta-neuron --lib`，再链接同一个 FFI。原始源码和锁文件保持一致；最终共享库 SHA-256 与前次构建**完全相同**，因此上述测试和计时对应的可执行字节也由干净构建得到。记录见 [NATIVE_CLEAN_REBUILD.json](evidence/NATIVE_CLEAN_REBUILD.json)。

`NativeFastBridge.tick_pair` 提供 V1 回执字段兼容的接口，额外说明传输方式和 FFI 计时。`native_features_fast` 从相同的两个八维公开观察生成相同的 40 维激活/资格特征，支持完整 JSON 回执；不接收目标标签、评价器或后续动作结果。关闭回执文件只改变传输/记录工作量，不产生效用证据，正式实验仍需保存输入和决策的完整来源。

原生调用仍返回 `DENY_ALL`、`requires_calibration=true`、`native_owner_integration=false`。C ABI 使用调用方提供的有效且对齐的缓冲区，不保留指针；有限值检查在 Python 和 Rust 两侧执行，Rust 的可捕获 panic 不跨越 ABI 边界。该局部研究接口不等于 Agentd 的生产接入。

## 契约验证

完整结果见 [NATIVE_FFI_CONTRACT.json](evidence/NATIVE_FFI_CONTRACT.json)。比较忽略计时、可执行文件身份和新增传输标记，其余 V1 回执逐项严格相等：

- 512 例两轮调用、1,024 次原始 tick，覆盖 1–8 维输入、正负边界、零值、激活相等、第二轮缺省、重置、Unicode 和 256 字节 scope；整数激活、资格、阈值、驱动、全部摘要、序列及权限一致。
- 64 例并发、32 例重复调用与独立参考一致。
- 80 对公开特征回执，包括正常/重置两个条件；40 维特征、完整/紧凑路径及同一个冻结读出头的动作一致。
- 18 例 Python 层错误输入或库身份错误、12 例直接 ABI 错误输入/指针边界均被拒绝；原生错误不改变输出缓冲区，之后的有效请求仍得到正确结果。

这里检查真实内核与传输契约，不把随机测试向量或合成读出头解释为训练效果。

## 成本测量

[NATIVE_TRANSPORT_BENCHMARK.json](evidence/NATIVE_TRANSPORT_BENCHMARK.json) 保存全部 120 个测量块、随机顺序、公开输入/读出身份、分项计时和进程启动记录。每块 64 例，24 次重复；每次重复对五条路径随机排序。所有原生路径使用完全相同的两个输入事件、整数内核、读出头和动作。历史路径使用相同维度的线性读出工作量，只作成本参照。

| 路径 | 每例 wall 中位数 | 24 个测量块均值 |
|---|---:|---:|
| V1 JSON 进程桥，完整回执 | 207.92 μs | 224.75 μs |
| V2 FFI，完整回执 | 101.96 μs | 109.44 μs |
| V1 JSON 进程桥，不写回执 | 169.84 μs | 175.07 μs |
| V2 FFI，紧凑状态、不写回执 | 40.67 μs | 41.49 μs |
| 简单历史特征和同尺寸读出 | 1.40 μs | 1.47 μs |

预先构造好 ABI 输入后的 200 次直接调用，中位耗时为 11.46 μs，其中两个原始 tick 合计 8.12 μs。直接调用数不包含公开特征哈希、编码、读出或 JSON 记录，不能替代上表完整路径。

另在 8 个新解释器/进程中交替测量两条传输路径。加载加首次请求的中位数为 V1 2.319 ms、V2 0.931 ms；测量从 Python 导入完成后开始，操作系统缓存仍可能复用，所以不称为完全冷启动。

当前机器由多任务共享，没有独占 CPU。完整回执使用缓冲写入，没有 `fsync`；不含模型生成、公开预览提取或最终交付时间。因此这里是透明的本机工程测量，不宣称生产延迟、能耗或端到端成本优势。完整记录与不记录的路径分别比较，不能把删除记录的收益全部归给 FFI。

## 复现

先按 V1 的 `restore_native.py` 在新目录恢复精确 crate、工具链和原生参考可执行文件；然后在仓库根目录运行：

```bash
python -m experiments.multimodal_output_portfolio.field_bridge_v2_20261027.build_native_fast \
  --compiler RESTORED/toolchain/bin/rustc \
  --native-receipt RESTORED/BUILD_RECEIPT.json \
  --native-workspace RESTORED/build \
  --out NEW_FFI_BUILD

python -m experiments.multimodal_output_portfolio.field_bridge_v2_20261027.native_fast_tests \
  --ffi NEW_FFI_BUILD/libhepta_field_bridge.so \
  --legacy RESTORED/build/target/release/examples/parameter_field_bridge \
  --out NEW_NATIVE_CONTRACT.json

python -m experiments.multimodal_output_portfolio.field_bridge_v2_20261027.native_benchmark \
  --ffi NEW_FFI_BUILD/libhepta_field_bridge.so \
  --legacy RESTORED/build/target/release/examples/parameter_field_bridge \
  --out NEW_NATIVE_BENCHMARK.json
```

本次执行库 SHA-256 为 `bfad6ca9d91d958296fa47c7f8ace4414b7ddf659e079ae5394c37bd104ceac3`，构建回执见 [NATIVE_FFI_BUILD.json](evidence/NATIVE_FFI_BUILD.json)。不同路径和链接器下，独立构建不预设二进制字节一致；先核验来源，再运行严格语义对比。
