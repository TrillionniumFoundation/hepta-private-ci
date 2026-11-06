# Supervisor Unix 连接期限候选：独立审查增量

正式结论为 `ACCEPT_STATIC_SOURCE_CANDIDATE`，源码阻断 0。只接受固定 ac18/c3e9 基线上的三路径候选 tree44e8；不确认旧两次 60 秒超时的根因，不转授编译、格式或原生测试资格，不修改 blocker 状态。正式实际 REVIEW blob 为 `35b07140231fa056026ca00088930873a4812b55`，完整 create/full GET 见 `REVIEW.actual.receipt.json`。

本增量不重复作者已冻结的 77 个原件，也不包含临时 partial Git 对象库。作者原 FREEZE 为 `79031a80b8b095fbffda0215aa67ddd7c6f0634f`。恢复时先按作者 FREEZE 还原这些原件到任意 `<author>`；把本清单各文件原字节放进 `<review>`。

运行只读独立验证（只向新的 `<output>` 写证明/临时 Git index）：

```bash
python -B <review>/verify_independent.py --source <author> --review <review> --output <new-output> --old-terminal <restored-old-terminal>
```

`<restored-old-terminal>` 是原包 registry `23e67ce20a439e2968eb63ae4e9a74a214ccd081` 恢复的 `old-donor-terminal-20261106T0840` 根。脚本实际读取其中完整 impact test log，核两条小 trace 的源字节偏移、完整摘要和逐字节相等。这里不再次打包那份完整日志或 ZIP。作者包内已保存完整对应身份和原小片段。

该独立 verifier 验证 77 个 frozen identities、21 原源绑定、7 primary GET 对应、3 reviewer fresh full GET、全部 10802/10804 叶与53实际根项，并用真正 Git index 正向/反向 apply 将整树 c3e9↔44e8 还原。首次执行 exit0/空stderr，原 stdout 14,319 B 保存在 `independent-01.stdout.json`。里面保留实际调用的绝对路径；异目录重放应检查 exit0/空stderr及所有断言，不能把另一个绝对路径的 stdout 谎称原字节相等。作者原 verifier 的异目录重放输出则是稳定的3332 B，已逐字节等于作者 static-02。

`references/supervisor-lib.rs` 来自先前固定的 causal source 包，独立绑定 ac18 全树内原叶，证明外层 `#[cfg(unix)]` 不变。三份 reviewer fresh GET 只读 Git对象，不查询 CI。

保留 `initial-review-helper-failure.json`：最初独立复制脚本误用 FREEZE 的 files 键，实际 schema 是 members；它在运行作者 verifier 前失败，修正读取键后重放成功。此为审阅工具错误，既不是产品故障，也没有修改冻结作者代码。

本次未执行 Rust、Bazel、Cargo、真实 socket、CI；未创建 commit 或修改 ref/PR。
