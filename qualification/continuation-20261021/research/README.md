# Research evidence checkpoint

此checkpoint同时保留三类不同证据：历史 Memory Qwen **40 calibration + 72 evaluation** 的当前重验、本轮托管 Laya Reader **64次新模型调用**，以及真实执行的 Rust scoped 资格。所有结果保持 **SHADOW_ONLY / DENY_ALL / NO_GO**；未训练、未生产激活，也没有将Reader64替代为Memory112。

## 主要结果

- 历史两个Memory归档按GitHub artifact摘要验证，再用当前 #1452 exact source重放：272文件通过。原生成run最终failure；后续只读归档verifier成功。任务是已暴露开发资料，独立新source families=0，semantic judge=false，科学/生产验收未成立。
- Reader #2969 source ca2768978429a2c9a98641fa2d58a8f587b88874 的 run39524743076/job118976636455 实际执行16任务×4臂×1呈现=64次predict。manifest、源码blob、逐行标签和summary均独立核验；温度clamp/未校准confidence、缺完整概率向量和checkpoint inventory等限制仍保留。
- 原 f740 Memory真实271通过/1失败/7跳过；exact0cb负控仍失败。原样移植现有 #2743 的两行 ordered 1..15历史断言后，在当前综合树+TLS锁的最终组合，Memory库272通过/7既有ignored、cargo-bin2通过，两项strict scoped Clippy exit0，justfmt后字节未变。未声称完成7个ignored probe、全workspace或Windows/macOS资格。

## 文件索引

`RESEARCH_STATE.md` 为详细报告；`research-checkpoint.json` 为结构化总结果。`MANIFEST.json` 列出本checkpoint全部文件的bytes/SHA256；每文件严格小于400,000 bytes且均为UTF-8文本。

| 证据 | 入口 |
|---|---|
| 历史112输出当前重验 | archive-reverified-current-source.json 与同名log |
| 原run/后续归档run状态 | original_run.json、original_jobs.json、archive_run.json、archive_jobs.json |
| 跨attempt归档来源 | calibration-shard-runtime-attempts.json、evaluation-shard-runtime-attempts.json |
| 实际artifact原始文件身份 | ARTIFACT_ENTRY_HASHES.json、historical-release-SHA256SUMS、historical-independent-SHA256SUMS |
| 新Reader64核验与完整保留的非权重report | reader-2969/independent-verification.json、reader-2969/extracted/ |
| Reader证据归属修复 | reader-context-bindings.patch、patch-files.json、qualification-suite-final.log、reader-independent-review.json |
| Native最终272+2与Clippy | native/final-validation-summary.json、native/final-combined-*-result.json及logs |
| 既有fixture owner来源 | native/migration-owner-current.json、native/migration-owner-files.json、native/migration-v15-existing-owner.patch |
| 终态资源快照 | local-model-resource-final.json |
| 未纳入raw及恢复入口 | RAW_OMISSIONS.json |

最终native测试时的源码为 prospective combined commit **6b074e52621d77338112f02119beb0cb1a6f869f**、tree **cc6170562020d8271196cbdf9d0e71fde7955ded**，加3文件未提交diff（fixture+两个锁）。完整diff SHA256为 **99ba4b1d81447b477e44bf414f8da398739746f74b591c3e30a8b31385a232a1**。后续发布commit由root单独建立绑定；不把本地组合测试冒称为尚未发布head的CI结果。

## 固定来源

- [Memory current owner #1452](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/1452)
- [Historical generator run38423223376](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/38423223376)
- [Archived verifier run38590620658](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/38590620658)
- [Reader new execution run39524743076](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/39524743076)
- [Existing V15 fixture owner #2743](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/2743)
- [Pinned Reader source tree](https://github.com/TrillionniumFoundation/hepta-private-ci/tree/ca2768978429a2c9a98641fa2d58a8f587b88874)

## 可复现范围和源片段导航

这是紧凑的审阅证据集，不是完整训练/推理环境。ZIP、完整job log、48-file replay closure及完整repo/native缓存未复制；保留来源URL、内容哈希、选摘及实际执行结果。要重跑原verifier，应先按 RAW_OMISSIONS.json 恢复缺少的原始材料并匹配摘要。receipt中的绝对cwd/log/cache路径记录历史执行现场，不作为可长期打开的链接。

六份 `reader-2969/source/` 文件必须保持精确原始字节，其内部相对引用属于上述 pinned Reader source tree 的完整仓库布局。它们是source snapshots，未包含相关文档站的所有依赖；请在固定SHA仓库上下文访问内部链接，不应改写源字节来使选摘目录看似完整。
