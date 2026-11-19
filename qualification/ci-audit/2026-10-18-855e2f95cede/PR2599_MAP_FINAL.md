# PR #2599 源码与源图最终检查

- UTC：2026-10-18T15:25:19.427943+00:00
- 真实 GitHub candidate：`19c5cd41c17dd42da7afac96203a4bc7901e23a6`
- Tree：`4c8ad58586a50f678396dbac4df3623b8dc6f314`
- Source parent：`e21417abcedda77d73a08b1417522966dc2d1c0a`
- 原 PR head：`1ebb9b8a9313e6504d2ebf9597412f3fe9c49d9e`
- 完整 checkout：`/dev/shm/hepta-github-inventory-855e2f95cede/repo`；clean，hidden index entries=0。该目录位于 RAM 临时文件系统，易失；通过已批准的 escalated exec 访问。
- 本 Agent 未更新远端 ref；发布与 fresh lease 由 root 负责。

## 已完成的真实范围

四个 Rust 文件使用独立审查过的 typed Result 修复。两个源文件的生产代码前缀与 main 逐字节一致；cfg、权限、签名、重放与撤销断言保持。Rust 1.95.0 下 scoped just fmt、git diff --check 及独立静态审查通过；本 Agent 未执行原生编译/测试。

原始、未改动的 CLI migrate 为四个模块生成 map：kernel.authority、kernel.evidence、runtime.agentd、runtime.fleet。四图仅 sourceBase/sourceObjects 有变化，其他 JSON 字段完全相同。sourceBase 全部指向实际 source commit e21417abcedda77d73a08b1417522966dc2d1c0a/tree10c2b68e495646a93355e059a2573271fdd1849d；所有执行、独立验收、激活、发布 claims 保持 false。

| Map | Git blob | 严格源码路径数量 |
|---|---|---:|
| kernel.authority | `be5c5c03e1fdd98049bd4c1cdec78da930e4e1a1` | 13 |
| kernel.evidence | `1b1a6b3e45d2652c22d387d696a9c7462d1bdece` | 10 |
| runtime.agentd | `8b1312a59c89c2152bc2732181b2446d4b72e063` | 16 |
| runtime.fleet | `bfc1ad4c717df0734063aab2919cba37f7d66590` | 4 |

## 严格验证结论与保留失败

四图通过原始 verify_source_identity（qualification、check_checkout 默认 true）、真实祖先/tree 校验和 sourceObjects 校验；全库原 CLI 的逐模块完整检查也未报告这四图失败。没有更改 registry、validator、source selection 或检查矩阵。

全库 qualification 仍 FAIL：main 为 29 个模块失败，source-only candidate 为 30，最终 candidate 为 26。最终失败集合严格等于 source 候选失败集合去掉这四个已修复 map。新源代码引起的 kernel.evidence 漂移已闭合；其他历史失败保持可见。不能将四图通过称为全库通过或生产资格。

以下三个受影响 map 保持原字节：kernel.operations、learning.plasticity、runtime.supervisor。其旧 sourceBase 8914a46dfc5984532f03dd2d559bf547ca4f1e69 与 main 为 14/45 分叉；完整非浅克隆证据证明它不是当前 candidate 的祖先。原迁移器因此拒绝，未通过内部 migrate_map 绕开旧身份入口，未添加 override 或伪父项。旧 map 原文和所有失败命令保存在 checkpoint/maps_before 及对应 JSON receipts。executionEvidenceTransferred=false 是 checkpoint 声明，没有添加仓库 map schema 字段。

## 原始命令结果

- `python scripts/hepta-implementation-maps.py verify --profile qualification --expected-sha 19c5cd41c17dd42da7afac96203a4bc7901e23a6 --expected-tree 4c8ad58586a50f678396dbac4df3623b8dc6f314`：exit 1。
- `python scripts/hepta-module-docs.py verify --profile qualification`：exit 1。
- `python scripts/hepta-module-docs.py refresh-derived --check`：exit 0。
- `git diff --check 1ebb9b8a9313e6504d2ebf9597412f3fe9c49d9e 19c5cd41c17dd42da7afac96203a4bc7901e23a6`：exit 0。

验证器脚本 Git blob：`e8ae0fd675b7e3ca2911b80af92cc21021789fbe`，未修改。

## 剩余严格验证失败模块

platform.types、kernel.operations、runtime.supervisor、runtime.codex、auth.authbus、secrets.heptabao、inference.control、inference.worker、objective.compiler、utility.ndu、neuron.runtime、prompt.optimizer、intelligence.control、cognitive.store、cognitive.read、memory.retrieval、memory.federation、knowledge.graph、learning.ledger、learning.operator、learning.eval、learning.artifacts、learning.plasticity、automation.taskflow、control.runtime、control.engineering。

## 源码一致性

| 文件 | Git blob |
|---|---|
| `codex-rs/hepta-agentd/src/automation_effect_host.rs` | `52db47a0fa1cb564eafbd4ee4a56127cb3ac3aba` |
| `codex-rs/hepta-agentd/tests/kernel_evidence_product.rs` | `6d2ffd978bb926f941dd17a66011060079f2fabd` |
| `codex-rs/hepta-agentd/tests/plasticity_process_e2e.rs` | `ef9c48e12826b0d49ed5213675b2a94e58fe728a` |
| `codex-rs/hepta-fleet/src/authority_port.rs` | `848a3e67ed96a3526c8a862d103e7946e8101845` |

## 未完成资格

Native compile/test/Clippy、本次真实远端 required CI、跨平台覆盖与独立产品验收仍需要各自证据。当前只支持源码导航和声明证据检查；不支持 build、execution、activation、release 或完整 CI success。真实模型实验调用数为 0。
