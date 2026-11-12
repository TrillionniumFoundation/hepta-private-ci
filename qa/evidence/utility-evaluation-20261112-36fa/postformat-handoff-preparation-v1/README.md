# 实际 postfmt 向 non-Rust 收尾的最小交付

此包是采集请求，当前保持 **WAITING**。没有执行采集、extractor、formatter 或测试，没有写入最终源码。它复用已冻结的 f868 extractor、ffaab fence matrix、432b WAITING 模板和原 QA 迁移方案，不新增资格门槛。

## 先送小件，再送实际文件

原 native fix/fmt 结束后，优先送两份 `*.execute_logged.original.json`、两份 stage terminal、最终 `RESULT.json`、实际 normal supervisor 原 SDK、`final.git-state.json`、`final.postimages-summary.json` 和 `ARTIFACTS.json`。原 runner 的 returncode、timed_out、output_limit_exceeded 必须按原值保留；f868 的原条件仍要求真实 fix/fmt 均为 0 且未超时。任何失败或 Unknown 都按原件交付，不能写成成功。

这些小件和完整实际源码证据到齐后，可以由 Root 审核并开始 proposal 工作，不必等待所有大 raw 日志完成离机传输。原日志仍须完整保留并继续归档，不能用摘要代替原件。

## 完整清单与 73 个实际文件

必须保留原 51181866 inventory 函数产生的**完整最终清单**及完整 `final.postimages`，包括限定文件组以外的变化、untracked 和 ignored 项。73 个文件只供准备 marker、QA 和 allowlist，不能替代全源码清单或全 Rust collector。

`CAPTURE_PATHS.txt` 给出精确路径集合：

| 分组 | 数量 | 用途 |
|---|---:|---|
| 冻结 matrix 的 Rust 路径 | 46 | 原 39 项迁移、10 项新增保护、382 selectors、17 literals、10 mounts |
| 已有 QA 两份清单的并集 | 21 | 取得实际 preimages，逐方法保留原断言和攻击；不是新增修改范围 |
| 支持文件 | 6 | 当前 CALLERS、allowlist、原 verifier、typed helper、Root workflow、新 ports helper |

每个文件交付实际完整 bytes，以及 path、kind、mode、bytes、SHA256、Git blob identity、稳定读取记录；可用 base64 传输。文件缺失、删除或不稳定必须明报，不能用 preformat blob 填补。只有精确 46 个 Rust keys 写入 f868 的 `formatted_source_pins`，其余 27 件属于独立上下文。

文件字节身份应比对完整 inventory 的 `bytes`／`sha256`／`working_blob`，权限和 mode 比对实际物理记录。真实 fmt 改动可以使 `matches_index=false`；不得误用旧 `index_blob`／`index_mode` 覆盖实际工作树 bytes 或模式。

可以把这批实际文件编码成一个 gzip/base64 包；大于单 blob 限额时，用最多 262,144 decoded bytes 的分片，给出所有 encoded/decoded 与整包身份、顺序及重组说明。清单和路径组无需等待大日志离机。

## 正确填写身份和冻结窗口

`source_identity` 必须直接复制完整实际 inventory 的 `source`。维护期间预期 HEAD 为 `9c4a11f…`，其 Git tree 为 `ee42ec7e…`；实际 working-tree physical Merkle 单独取 `final.postimages-summary`，不得把它填进 HEAD tree。真实 dirty/clean status 原文同样保留。

提供实际协调这个源码目录的外置 lock/lease，以及禁止写源码的时间窗口。f868 会取该锁的 nonblocking shared lock，再做全 inventory before/after 等值检查。不能拿无关旧 worktree 的锁或只用于旧 advance 的锁冒填。该信息缺失时保持 WAITING，由 Root/native 明确实际协调方式。不要为此改已冻结或已运行的 v4；采集复用原证据并在其完成后作为独立只读步骤进行。

Root 已认可一个最小待实施方案：固定任务外置 `SOURCE_COORDINATION.lock`，由 launcher 在 exec 前实际取得 nonblocking EX 锁，保留 inheritable fd 穿过 exec，直到原 v4 主进程结束。采集器和 f868 随后对同一个实际文件取 SH；本任务后续 native 源写者统一取 EX。原 v4 字节、fix/fmt argv、预算和环境不改。优先沿用等价的实际协调机制；当前实际 path／lease 字段仍为空。锁只约束本任务的合作写者，不回溯旧运行，也不替代完整 inventory 前后核验。

最终启用合同仍由真实记录填写：run identity、Root review blob、实际完整 inventory 身份、46 个实际文件 pins、真实 lock path、fix/fmt 原 JSON 指针。当前请求不填这些未来值。原 v4 的 `git_blob` 字段可映射为 f868 的 `git_blob_sha`，只改引用字段名，不改原 JSON 证据字节。

## 最终工作保持原范围

历史 86dd／383ab 是计划来源，不是实际 postfmt 产物。源内 verifier／typed helper 必须匹配冻结 matrix 的精确 pins；若真实 fmt 改变它们，先保留变化并交 Root 复核，不能自动降级检查。

保留原完整 Rust collector、`source_roots=(codex-rs,)` 和原三个 product-only ignored fragments；不提前把测试或示例排除出 authority/field 输入。原 Root workflow 的 32＋1 个必要 case 从最终实际 workflow 读取，ignored UID0 case 不算默认通过。

最终 non-Rust 修改仍由 ordinary_path 单人准备：明确记录迁移的方法，保留每个旧断言／攻击；不继续沿用早期“140 函数 AST 全未变”的阶段性结论。最终 marker 和 CALLERS allowlist hash 只从经过复核的实际 bytes 生成。采集和 proposal 不证明真实 A/B/C、普通部署、daemon/Root 恢复或资格通过。
