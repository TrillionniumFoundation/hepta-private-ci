# v3 发布准备审查

本任务只读核对本地源码和证据，只新增此报告及 PUBLICATION_PLAN_V3.json；没有修改 scripts、执行模型/训练、操作远程或 Git、读取新 C。

## 可立即开始的代码层

沿用 #6440 的 stacked Draft PR：base 为 `codex/cell-experiments-v2-20261116-0c078a-s23`，head 为 `-s24`，head commit 为 `42e32825ae20d460cb782856e00816661536853a`。JSON 采用代码优先顺序，每层独立 Draft，后一层以此前一层为 base。

**没有发现稳定 20 个新模块的源码级发布阻断。** 新模块共 5,357 行，最大文件 469 物理行，最大 AST statement 数 235；44 个冻结旧 Python 文件的 SHA256 全部保持原样。15 个 package 代码层全部低于 500 新增文本行。C01-C12 可先行；SQLite C13 之前插入 E02 固定历史 destination 源码。C08 的 fixture 来自 C02，C12 的 fixture 来自 C07，依赖顺序已列明。

中间层只是审查边界，不能称为完整候选。47 测试记录只属于最终完整的 64 模块快照，不能逐层复用成该层的通过证明。正在变化的 root-owned Qwen launcher 留给后续冻结操作源码层，不计入稳定 20 模块的审查结论。

## 大小例外只在不可变证据

E01 的历史 ACT-2 frozen manifest 是 1,890 行；E14b 的 Smol member index 是 1,739 行。二者各自单列机械证据例外，不伪称低于 800，也不为减少 diff 改写原字节。其余当前计划层均不超过 800。若发布门槛不接受此类例外，单独暂缓这两层，并另确定保留原字节的 artifact 表示；前序代码层无需因此停下。

## 测试与格式化证据

- `PREFORMAT_TESTS_02.log` 的 SHA256 与 receipt 一致：47 项中 **44 passed、3 skipped**，exit code 0。
- 其 64 文件 inventory 与 `source-before-fmt-02.zip` 完全一致。
- `FORMAT_01.json` 记录 `/opt/homebrew/bin/just fmt` 在专用 formatter workspace 的 `codex-rs` 执行，exit code 0。
- formatter 的 before/after 哈希对应已测试源码和当前 64 文件；格式化归档与当前文件一致。
- AST 差异仅涉及 source_metrics_v3 与 sqlite_agent_probe_v3 的 docstring 缩进；仅规范化 docstring 后，全部 AST 相同。本任务没有在格式化后重跑测试。
- formatter 工具基线 `f8e54c63700c8ffc40c9ddaec4e3fd44817da0fb` 与发布基线是不同身份。

本任务另核对了新入包 numeric-01 的 source/log hashes：exit 1，模块导入阶段失败，三项数值测试没有执行。随后 root 已观察 numeric-02 原 job `1a1e6e5ab62-392-3c80` 的三项真实 Torch CPU 测试全部通过，运行时为 torch 2.9.1+cpu / transformers 4.57.3 / peft 0.18.0；root 将保留原日志和 receipt。本任务不把尚未自行核对的 numeric-02 原件标成已审查。

发布应分别写本地 44+3skip、numeric-01 import failure、numeric-02 三项 CPU pass；不要覆盖早期记录，也不要把数值测试当成任务能力或完整 E1-E6 结果。唯一剩余证据收口要求是把 numeric-02 原件单独入包，准确限定范围后不阻断代码发布。

## 原始执行快照不能互换

Smol archive SHA256：`7d822083fd95b790a3d39196fe960f7e2848b9b971b2463622703d4ec316a95f`。已与 launcher 的 expected digest 核对，含 47 个 package 模块。当前包有 64 个；development_readiness_v3 与 repo_interaction_v3 存在真正逻辑差异，protocol_v3 另有格式差异。旧 Smol 运行不得改挂当前源码。

本任务完整核对的 QWEN_SOURCE_01 SHA256：`6d471456bfcf6e7a9ade52ea995317f9c0894571d9bd5ebe96dcb845d68e58ad`，其 64 个模块与当前源码及 manifest 一致。root 后续 SOURCE_02 为 `38a6f8bbc8a602befcd45ebd919bbcb2eca12d9f105798b29d72b2eb051c42d7`，报告补入 32 个既存依赖、删除 2 个旧 confirmation 文件、64 core 未变；SOURCE_02 与其运行结果另保留，不沿用 SOURCE_01 的完整核验身份。

Smol 原运行的新 evidence、FREEZE、READINESS、member index 已由 root 写入，并列在 E14a/E14b；本任务只清点新入包文件，原回执内容由收集方负责核验，不再声称这些文件缺失。所有后续环境、模型、拟合和采用证据继续独立成层。
