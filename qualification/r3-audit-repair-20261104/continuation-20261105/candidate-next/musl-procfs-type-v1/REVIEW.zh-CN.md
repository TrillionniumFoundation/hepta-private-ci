# musl procfs 类型兼容修复（未执行候选）

实际 5b musl 构建在 `parent_lifecycle.rs:122` 报 E0308/E0277：`statfs.f_type` 为 `u64`，`PROC_SUPER_MAGIC` 为 `i64`。原 canonical platform、outer/inner 与两个 Rust action 的 musl target/linker/stdlib 校验已成功；实际构建退出 1，尚未到 ELF 或 `--version`/`--help`。原运行是 41999115065 / job 127149584475，checkout 9063c52a，树与产品 5b 相同。完整来源和原命令见 [manifest.json](manifest.json)。

## 唯一源码改动

```rust
|| i128::from(filesystem.f_type) != i128::from(libc::PROC_SUPER_MAGIC)
```

[694 字节补丁](candidate.patch) 只替换原比较一行。`i128` 可无损表示全部 `i64` 与 `u64` 值：GNU 的负值仍与正 procfs magic 不等，musl 的大无符号值也不会截断后误等。固定 libc 0.2.191 主源给出 MUSL `c_ulong`、GNU `__fsword_t = i64` 与 magic 的 `c_long` 定义；Rust 1.95 原 `From` 实现支持这两种转换。主源全文及身份在 [primary-sources.json](primary-sources.json)。未声称此次重新核验 libc registry archive 与标签源码的完整等价；当前真实编译错误已独立证实实际端点类型。

原 FD 身份、CLOEXEC、只读/unread、procfs 拒绝顺序、退出中父进程判据及用户 fork 前关闭全部保留。三个父生命周期控制及 ignored 支持子入口逐字不变，不添加常量镜像测试，不改 workflow、依赖锁、预算、重试或断言。

## hygiene 因果更正

这不是前轮 `just fix` 删除类型转换引入。原 App 候选生产 blob `ffc5774508ab4a069a6bcb70f27950300b86fbfe` 的第 96 行从一开始就是直接比较；实际 scoped fix `e43c9285b0060eb7b8f6dc9f18692ac3d1167894` 只移除了测试中 `st_dev/st_ino` 的两个同型 `as u64`。随后原 fmt 把比较排至第 122 行，表达式未变。因此这是原新增生产代码未兼容 musl ABI 的缺陷。完整原对象链见 [hygiene-causality.json](hygiene-causality.json)。新 GNU `i64 → i128` 是真实拓宽，不能按先前 `u64 → u64` 同型转换来论；仍需原后续 lint 验证。

## 证据与下一原门

隔离云目录中实际 `git apply --check`、apply、reverse-check、reverse 均成功，前后全文精确匹配，见 [roundtrip-receipt.json](roundtrip-receipt.json)。这不属于编译或运行资格。research 已窄审完整一行差异、ABI 原文与报错对应，未执行新编译。

后续需由唯一 CI 执行者在绑定的新源码上完成原 musl workflow：真实显式 musl 目标构建、原 static ELF/hash 校验和两次 CLI 进程 smoke。原 GNU owning 控制与 fix/fmt 可随根代理安排的联合源码批次执行；GNU PASS 不能替代 musl 编译。当前未启动 native/CI，未改产品 ref；完整 musl 行为与 Alpine 部署验收仍不在本片覆盖内。
