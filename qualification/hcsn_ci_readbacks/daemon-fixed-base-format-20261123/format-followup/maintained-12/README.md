# 普通 Rust 源的固定基址复验

在本目录执行 `python3 verify_active.py` 可从已存逐行记录核对全部 4,175 个路径，恢复原来的 4,219 项有序清单。检查器借用上级目录的 `registered-44.zip`。

在含 e4be1e97 和 97a379c5 的同仓 Git checkout 上，传入 `--repo /path/to/hepta-private-ci --rustfmt /absolute/path/to/official-1.96.0/bin/rustfmt` 可复跑全部原文件并逐字节生成候选 12 个后像。检查器把 Rust 源与配置读取到临时目录，不改工作区。

| 定位 | 原源码结果 | 原生所有者现状 |
| --- | --- | --- |
| prompt/agentd/compiler/intelligence 四个文件 | 原 Rustfmt 存在差异，源自四个独立 V3/V2 实现提交 | 当前包源内未找到四个模块的接线。原 context.compiler 验证器对既有清单就拒绝 `source identity policy`。它列的 26 个路径有 5 个在原树缺失。 |
| memory-federation-wire 五个文件 | 原 crate 的 lib.rs 注册了模块及测试 | 父工作区中没有注册该 crate。其原生包测试无法证明该版本的产品接线。 |
| supervisor 三个文件 | 当前 Rust 模块目录内保留其原提交 | 父模块未引入这三个模块。`qualification_fault.rs` 自带的非 qualification 拒绝副作用测试可单独编译。 |
| 其余 4,163 个 | 同一 Rustfmt 检查通过 | 实际使用原 CLI 的 edition、输入顺序及逐目录配置。 |

[原未预格式化头](https://github.com/TrillionniumFoundation/hepta-private-ci/commit/e4be1e972707f5c376033fd59e18fb4f260da891) 和[独立的 12 文件格式候选](https://github.com/TrillionniumFoundation/hepta-private-ci/commit/97a379c5a347f0e66c5ed9a0cbd38303d1f92cb5)保留完整历史版本。12 个文件从 Rustfmt 产出，未改动编译接线、模块注册、授权和已有证据。独立 Rust 编译器 1.96 的 unexpanded pretty-printer 对9个文件生成字节相同的正规化源码。其余三个文件有7个表达式使用大括号包围，3份逐行差异保存在 `rustc-normal-3.patch`。这种语法级检查不测量程序集运行行为。

`history.json` 记录每个源当初的原提交身份。`sources.json` 保存原/新 Git 对象和 SHA-256。`changes.patch` 来自两个精确文件版本。`context-owner.json` 比较的是当前树与其原映射 observed sourceObjects；当前清单原本就不含脚本要求的 exactSourceEvidence 结构，不应将其作为四项已经通过原生资格的证据。

在 Git checkout 上运行 `python3 verify_wiring.py /absolute/path/to/repo` 可重新读取两端各 1,842 个 Rust、TOML 与 Bazel 文件，核验文件 Git 对象并重新获得相同的模块引用结果。该范围不涵盖运行时生成的模块。

## 原 fixed-base 格式阶段的宿主结果

[单独源 97a379c5 的真实作业](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/45147536205/job/137600455141) 在 Ubuntu 24.04 运行原 `just fmt --base b8e8c6e82abc1479c573f61a5e17d28d581e6cad --check`，退出 0。随后真正运行同一命令的写入模式，退出 0。两次工作区探针均为零字节，原档案材料未被改写。两个命令与 Git 检查合计用时 248 秒，格式脚本的 41+3 项原测试通过。完整 daemon 的其余作业未在此轮重新运行。

两端都从 200 个实际 Cargo 包中确认 wire 包缺席。独立 manifest 两端均报工作区不含该成员。context 检查两端均因原身份策略而拒绝，supervisor 文件两端的独立原测试各 1/1，另外两臂均用 qualification feature 通过编译。运行 `python3 verify_hosted_candidate.py` 可直接用原始 ZIP 复验这些记录。
