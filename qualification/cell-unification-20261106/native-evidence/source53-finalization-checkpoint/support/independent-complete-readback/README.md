# Source53 最终 fix / fmt 独立闭合读回

本组独立读取了唯一原生 finalizer 的完整闭合数据及三份原源码归档。原 job 为 `1a1b2a75955-fc05-7f27`，自然退出 0。本地只运行 Python 数据读回；没有重新运行 Rust、Cargo metadata、测试、fix、fmt 或 Git 命令。

## 结果

- 原 `just fix --locked` 带冻结的 26 个 owner package，raw / effective / resources / outer 一致为 0。耗时 478.47458124160767 秒；原 `fix-only.patch` 为空，197 份源码与原 R31 的已测试源码逐字相同，没有 Git stage 子阶段。
- 原默认 `just fmt` raw / effective / resources 为 0，耗时 4.21239447593689 秒。选择保持原 HEAD、183 个 Rust 路径和 2 个 Python 路径；实际改变 54 个 Rust 文件和 2 个 Python 文件，全部位于允许范围。原精确 stage 命令成功，没有模式、锁、依赖或范围扩展。
- tested-pre-fix / post-fix / final-post-format 三 tar 各 198 regular members，分别含完整 197 源码及原 manifest。各成员的大小、SHA256、Git blob 与 Git regular-file mode 均重新计算。三份 patch 全文件正向和反向应用均精确，format-only 与 tested-to-final 两份原 patch 字节相同。
- controller 两段输出连续覆盖 stdout 8,595 字节、stderr 0 字节；原 raw、receipt 及最终事件均与完整保存流一致，outer 无取消、超时或自动重试。

已测试 source53 commit 为 `f74be175de66a4b351cd239d39d98cd34fe9cc1b`，tree 为 `440d4a8e09af4009e4d9ea067388826308da8803`。fix 后 tree 不变；原生格式化所得 tree 为 `42c1dd4e1a751c690c2800dfc3868e771dc9c70b`。原 `complete.json` 的最终 commit 仍为 null；后续实际发布另有证据，本组不修改原记录。

## 静态差异审阅

`STATIC-SEMANTIC-READBACK.json` 绑定实际最终 tar 字节。两个 Python 文件的 AST 完全相同。54 个 Rust 文件中，15 个非注释词法 token 流完全相同；其余差异为 279 处紧邻闭合分隔符的尾逗号、6 个文件中的 20 处块或分号调整，以及 9 个文件中的 59 处导入／模块声明重排。所有声明及附属 cfg/path 属性均保留，非声明的 literal / identifier / operator 顺序一致。逐处审查了块中的原 tail expression 或显式 return，未发现断言、deadline、retry 或 filter 弱化。

受改 Rust 文件中的 1,960 个 assert / debug_assert / panic / unreachable 宏序列保留，比较中只归一化已核对的逗号。原始词法差异及上下文完整保存在 `PATCH-LEXICAL-OBSERVATIONS.json`。这是一项词法、完整差异和人工上下文审阅，不是 Rust AST 或编译器形式证明。

## 必须保留的边界

原 fix 日志包含 3 个独立 warning 诊断：vendored i18n-config 两处 `mismatched_lifetime_syntaxes`，以及 Agentd `StatusDiscovery` 的 `large_enum_variant`。另有 3 行 summary，其中 lib-test 明确重复 Agentd 同一诊断。命令退出 0 不能称为严格 lint 全清；完整原日志、精确行号和 byte offsets 保留在 warning 读回中。

格式化后没有运行测试，R31 20,228 PASS 的资格继续绑定 `440d…` 已测试树；不转移到 `42c…`。科学 HOLD、权限 DENY_ALL、source53 diagnostic-only 与“未主张行为修复”保持。共享文件系统 free-space 样本不能当作该任务独占成本。

本组独立核了全部导出的 197 原始 Git blobs 和模式；未重建未导出的整仓目录对象。最终根 tree 是原生闭合记录的观察值，root 的独立 GitData 注册／树重建属于另一份证据。两个原锁的 raw bytes 从 R31 archive 读回，最终锁不变则由固定的原生 pre/post hash guards 绑定；它们不在 197 份 changed-source tar 内。

## 可重现入口

从原工作区根运行以下数据脚本，并给一个尚不存在的输出路径。脚本不会导入或执行项目代码：

```text
python3 source53-finalization-independent-readback/review_finalization_v3.py --output /path/to/new-readback-directory
python3 source53-finalization-independent-readback/review_semantics.py --output /path/to/new-semantic-readback.json
```

`extract_lexical_observations.py --output /path/to/new-lexical.json` 可重现较早的 patch-derived 词法观察；它保留当时尚未读取最终 tar 的原字段，实际 tar 的后续匹配证明在语义报告中，不回写历史文件。

最初两次本地 reader 因 `./scripts/…` 表示与 owner record 取 package 字段的适配问题停止。v1、v2、原 exit1 及两份 correction 均保留；v3 完整闭合 exit0。原生证据、源码和门禁结果未改变。
