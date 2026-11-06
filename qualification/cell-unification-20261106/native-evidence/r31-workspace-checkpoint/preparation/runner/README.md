# source53 r31 惰性工作区模板

本目录只保存执行准备，**未执行 r31**。模板为 `FROZEN=False`，21 个未知 source/apply/r30 闭合绑定均为 `None`。原 R29 执行器和 r30 V2 原文保存在 `references/`；旧准备或正式证据未改写。

## 启动前提

首先核对 source53 的完整 197 条源码、HEAD `bef6fa7645df9df12b69fda499e97eed25de6c75`、两份锁与独立 apply 原件。source50 原锁执行仍保留其历史身份；只允许已审核的五个非 build Rust 叶差异继承其依赖结论。source53 新增到 changed manifest 的两叶必须仍是仓库中已存在的 Bedrock 文件，source52 的 195 行逐字保持。

随后必须读取 r30 的 **19 份成功闭合原件和自然 outer 0**。两阶段严格为 app-server 的原 strict 和完整测试，重新解析 full log，后验要求原 **1,345 个 (binary, name) ID 恰好全部 PASS**。命令不使用这些 ID 作为 filter。r30 的原 source/lock/环境/receipt/resource/guard、完整 acceptance 和 complete 字段均独立核对。

source52 R28 的 26 份原件、Python 32 和四包 1,564 PASS 仅保留为历史继承。它们不能替代同 source53 的 r30 完整通过；本 runner 不重跑 Python。R24、R26、R29 的真实失败不被改标。

## 唯一将来的工作区执行

通过所有前置后，才在当前冻结源上运行全新的：

```text
cargo metadata --locked --no-deps --format-version 1
just test --locked --retries 0
```

两者 cwd 为任务 source/codex-rs。fresh metadata 必须证明 actual/default members 都是相同的 193 个包。工作区测试不带 `-p`、filter、额外 feature、ignore 或新的测试超时；外层合同仍为 9,600 秒，环境保持原 Rust 1.96/debug0/2 jobs/2 threads 和 20 GiB 空间前置。

原 R29 的完整日志、rows、readback 与旧 metadata 按固定哈希读回，重新建立 20,228 个 ID。旧 metadata 只解释旧结果，绝不充当当前 metadata。完整新门自然结束后，才要求执行集合与原 20,228 个 ID **完全相同且全部 PASS**；缺失、额外或不成功 ID 均不授予成功。所有实际行、footer、skip 原口径和原 rc 保留。

原 rc 在自然 wait 后先通过 create-only JSON 写入并 flush/fsync，再进行哈希、source postguard 和派生验收。派生错误不会覆盖原 rc；失败不会写 complete，也不会重试、自动清理或运行 fix/fmt。

## 资格边界

source53 是 **diagnostic_only=true / behavior_repair_claimed=false**。其门通过也不能单独证明 Bedrock 行为缺陷已修复，不能改写 source52 R29 的失败；历史科学 HOLD/部署边界不由本脚本更改。最终资格必须按将来的真实原件另行审阅。

`PRODUCER-CONSUMER-READBACK.json` 记录本地实际 AST/symtable、27 个 R30 共用函数逐字比较、19 原件字段合同、旧 R28 pins 和原 R29 command/wait/raw-first/postguard 核心保真。它是静态准备证据，不是 native 执行结果。
