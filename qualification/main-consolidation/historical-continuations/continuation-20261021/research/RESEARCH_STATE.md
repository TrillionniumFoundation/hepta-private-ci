# HEPTA Research / Memory 契约审计与修复交付

观察日期：2026-10-21 UTC。全程保持 **SHADOW_ONLY / DENY_ALL / NO_GO**。本地审查未调用模型；本轮新发布 #2969 的托管 workflow 已产生并核实 **64 次 Laya Reader 调用**。没有训练或生产激活。PR 当前元数据见 `pr-snapshot.json`；结构化结果见 `research-checkpoint.json`。

## 结论

1. 历史 Memory **40 calibration + 72 evaluation** 的真实模型原始输出、分片收据和归档实际存在。本轮下载两个 GitHub Actions 归档，核对 SHA256，并以当前 #1452 精确源码重新执行既有 verifier，**272 个文件通过，所得对象与原独立归档报告相同**。这属于历史推理证据的当前重验；Memory 40＋72 的新增推理为 0。另有后述 #2969 的 64 次新 Laya Reader 诊断。
2. 原生成工作流终态为 failure：32 个模型分片成功，evaluation collector 失败，原独立重验未运行。后续 read-only archive verifier 的独立工作流成功。两者必须分别记录，不能把成功重验描述为原工作流成功。
3. 112 次模型执行并不等于 112 个独立样本。校准为 8 个任务 × 5 个 k，评估为另 8 个任务 × 9 臂；独立新来源族为 0，人工语义裁决为 false。研究收益和生产验收保持未成立。
4. 在当前 #2714 的精确源码中发现并修复 Reader 证据归属缺陷：调用方可覆盖 payload 的 candidate/split/checkpoint，且双 runtime digest alias 冲突或空值可被 `or` 静默隐藏。修复保持兼容的旧 API、摘要和拒绝权限边界。最终全套 **125/125**、独立 Reader **40/40** 和 **158** 个额外案例通过。

## 当前 owner / source identity

| PR | Owner branch | 当前 HEAD | 状态 |
|---|---|---|---|
| #1452 | `codex/memory-cell-evidence-20261008` | `81d9fcb36bddfcc6dc914f87697c642824273cc1` | 非 Draft / 未合并 |
| #2688 | `codex/memory-cell-contracts-20261017` | `55088dd78b4950407f77a43f054efed0816409cb` | Draft / 未合并 |
| #2695 | `codex/group-ndu-deterministic-20261017` | `74bbcc9b0bb330649cd54d9881ae3676d3968bae` | Draft / 未合并 |
| #2734 | `shared-encoder-blocker-closure-rerun-20261018` | `dc271d4f47028e941decce70cc8ef81fb24d2141` | Draft / 未合并 |
| #2714 | `research/real-reader-intake-p4-20261017` | `f191cd081ba16fed8827a18093b5a5b39e9a36cd` | Draft / 未合并 |
| #2786 | `fix/memory-cell-fixtures-current-head-20261018` | `3a0a5f97cc1b126c4eb88fc8cede39818e6f97ae` | Draft / 未合并 |

这里的 owner 指代码分支归属；这些 PR 的元数据作者均为 ProfHepta，不代表独立研究审批者。PR body 多处仍写旧 SHA，当前 source identity 以 API metadata 为准。#2786 的 mergeable 为 false；其 base 元数据已不同于当前 #2688 tip，不能直接认作当前契约修复已经集成。没有对共享 owner 分支做修改或留言。

Reader 修复 parent：`f191cd081ba16fed8827a18093b5a5b39e9a36cd`，tree：`42865df641069d9a11285038e7d75b3df9111248`。已发布的隔离 child PR #2969 以 `research/real-reader-intake-p4-20261017` 为 base。#2714 自身原 base 是 `research/checkpoint-resource-binding-p3-20261017`，SHA `e08323af4805ed9a8d14afabf2212923195f2156`。精确 `reader_runtime_receipt.py` 路径在当前 #1452/#2695/#2797/#2963/#2961 不存在；全 PR 元数据盘点未找到直接接管这个模块的新 owner。原文件 blob 为 `7c12845f186c67d11238721c769b839b11f1e367`。

## 40＋72 的来源与可重复性

原生成 run：[`38423223376`](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/38423223376)，attempt 16，source `bc76ac57ba972bf105c71ddd997cd215cec5df2e`。后续归档 verifier：[`38590620658`](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/38590620658)，source `73f282338cbed20edee6cf945fadeef9983de265`。对应 API 响应保存在 `original_run.json`、`original_jobs.json`、`archive_run.json`、`archive_jobs.json`、`archive_artifacts.json`。

必须区分工作流最后状态与每个原始执行的 attempt：归档 calibration 的 16 shards 分布为 attempt 1×4、2×7、3×2、4×1、5×1、11×1；evaluation 为 11×6、12×2、13×5、15×1、16×2。所有 shards 的 run ID 和 source SHA 相同，原始输出跨多个失败重跑保留，并非 attempt16 全新执行112次。逐 shard 记录见 `calibration-shard-runtime-attempts.json` 与 `evaluation-shard-runtime-attempts.json`。

| 归档 | Artifact ID | SHA256 |
|---|---:|---|
| memory-disjoint-archived-release.zip | 11906888485 | `9305aa9c637601cc1efec844537ac4de57c52aaf83fbc1c6fb5a65aaa84defab` |
| memory-disjoint-archived-independent-replay.zip | 11906918262 | `ffb27c88fa665fd5a5f09d712d39a7552010090095c10b2550adeaa8420f85a8` |

解压前检查路径、展开总量和符号链接。历史 model 为 `Qwen/Qwen2.5-3B-Instruct`，revision `82f42baa094a9600e39ccd80d34058aeeb3abbc1`，model identity `f9aa334d3a02cabececea367c283caf66ef9875132907ebc34dac1c8d3a7f225`。模型文件记录为 6,183,463,389 bytes。raw rows 为 calibration 40、evaluation 72，与 scored rows 中保存的原始记录 112/112 相同。

当前重验使用 #1452 的 `81d9fcb36bddfcc6dc914f87697c642824273cc1` 源码。AST 依赖闭包共 48 个 Python 文件，逐文件 Git blob 与目标 tree 一致，见 `replay-source-identity.json`。执行现有 `strong_rag_receipt.py` 检查原始来源、prompt、模型指纹、评分、资源字段和配对对比；仅对固定配方执行确定性 procedure probe，没有加载模型。

```sh
PYTHONDONTWRITEBYTECODE=1 python3 hepta-audit/research/replay-source/strong_rag_receipt.py \
  hepta-audit/research/extracted-release \
  hepta-audit/research/extracted-independent/original \
  --generating-commit bc76ac57ba972bf105c71ddd997cd215cec5df2e \
  --output hepta-audit/research/archive-reverified-current-source.json
```

命令 exit 0，272 个文件通过。结果见 `archive-reverified-current-source.json` 及同名 `.log`；与 archived `reader-audit.json` 对象完全一致。此等价验证不提供新的独立研究审批。

## 实验结果与保留限制

校准 k1/k2/k3/k4 均为 4/8，k6 为 2/8；冻结规则选 k1。评估：

| 实验臂 | strict task success | 正确且有完整程序声明引文链 |
|---|---:|---:|
| selected_k | 5/8 | 3/8 |
| hybrid_k4 | 3/8 | 1/8 |
| hybrid_k6 | 2/8 | 0/8 |
| hybrid_k4_reversed | 3/8 | 1/8 |
| single_hop | 4/8 | 4/8 |
| entity_time | 8/8 | 4/8 |
| organized | 8/8 | 4/8 |
| program_support | 8/8 | 4/8 |
| empty | 0/8 | 0/8 |

有 39 对完全相同的 ordered-evidence/prompt，历史输出无答案、token 数或任务结果差异。这个结果只支持这批已执行输入的确定性一致性。organized/entity_time/program_support 的 8/8 task score 并非 8/8 引文链完备；三者均只 4/8 满足程序声明的完整支持链。语义必要性、充分性和独立人工裁决均未认证。

这些任务属于作者构造且已经暴露的开发资料。数据集键、来源隔离和冻结 k 的机械检查不能证明新来源独立性。独立 source families = 0，未来实际时间窗口观测 = 0，statistical superiority = false，production accepted = false。各臂共享问题的配对比较也不能被计作新增独立样本。

现有证据未补齐提取、建索引、存储、维护、撤销、恢复等完整生命周期成本；模型推理 token/CPU 指标不能独立证明经济收益。也没有参数记忆学习成立、已训练 critic、长期迁移或真实生产 cutover 的证明。#1452 的其它大规模 native census 声称不在本轮112份归档核验范围，不能由此顺带认证。

## 契约 fail-closed 范围

#2688 精确源码的 MemoryCell manifest/input/receipt/split validation 与 `run_memory_cell_tick` 在 recall 前验证 cell、graph/model generation、source/forget frontier、cue、snapshot/policy；tick 只返回候选 checkpoint digest 和 recall evidence，不添加 source writer、trainer 或 topology apply。Selected 状态与 checkpoint/recall 输出关系有显式校验。此处为源代码审查，不等于本轮 Rust crate/native gate 已通过。源码保存在 `source/2688/`。

#2695 精确源码 `SharedEncoderOwnerV1::encode_for_cells` 在输入/Cell 校验后调用一次 driver，再校验输出 digest/shape/range，并通过不可变 Arc 分享 feature。每 Cell head 验证 encoder/generation/Cell membership，Group gate 和 shadow System2 返回 `AuthorityPosture::DENY_ALL`。实现是边界与确定性基线；接口调用一次不认证底层 pretrained Encoder 的真实质量、训练或推理吞吐。四份精确源码及 blob 记录在 `source/2695/`、`shared-encoder-source-identity.json`。#2734 此轮确认 metadata/changed paths 和 owner；其 body 的旧 SHA/排队 CI 不作为当前模型/生产验收。

Reader 归属缺陷是研究证据完整性问题；原始 authority 已是 DENY_ALL。本补丁不声称修复生产授权绕过。未知字段维持 INCOMPLETE，缺失 context 的旧 API 仍可接受 caller context；匹配字符串或调用方补 join 本身不能认证来源真实性。

## Reader 修复及测试

只修改 runtime receipt adapter 和新增一个独立测试文件。candidate_id/source_split 若 payload 中出现，必须是与 caller 相同的字符串；external checkpoint 必须是合法 SHA，并与已有非空 checkpoint 一致。原来缺失/unknown checkpoint 的 join API 继续可用。两个 runtime digest aliases 若都出现必须一致，每个非 null 值都单独验证，不能以假值回退隐藏错误；缺失或纯 unknown 继续 INCOMPLETE。

| 文件 | Git blob | SHA256 |
|---|---|---|
| reader_runtime_receipt.py | `585c77d133f98bb29964c6ce71670f2af7676b33` | `1d2b1010980a2d0d521c81a7761423cbcd32fa50c30dc3d33f62197591837019` |
| test_reader_receipt_context_bindings.py | `a981f032581d2439ee3e8ff55291c3f2ec2ca884` | `a83ae9200ebc91dec3c9503d53cbec4ecab2cafc629970f00af86669ff1e7f7a` |

回归基线：原 current source 上 11 methods 有 36 个失败断言/subtests，说明不良归属被接受。加入 alias 负控后，首版 context 修复上 16 methods 有 14 个失败断言/subtests。最终 16 methods 全通过。完整 qualification suite 从原109提升到125，125/125通过、0 failure/error/skip。独立审查另跑 Reader40/40和158个原版合法输出/摘要等价及恶意输入案例。测试都是合成契约测试。

```sh
# cwd: hepta-research-fix
python3 -m unittest discover -s qualification/neuron-shared-encoder/tests -p 'test_*.py' -v
/tmp/hepta-wave2-tools/bin/ruff check --select E,F,I \
  qualification/neuron-shared-encoder/neuron_shared_encoder/reader_runtime_receipt.py \
  qualification/neuron-shared-encoder/tests/test_reader_receipt_context_bindings.py
/tmp/hepta-wave2-tools/bin/ruff format --check \
  qualification/neuron-shared-encoder/neuron_shared_encoder/reader_runtime_receipt.py \
  qualification/neuron-shared-encoder/tests/test_reader_receipt_context_bindings.py
```

最终补丁：`reader-context-bindings.patch`，SHA256 `01cf3e2804f6c7f9f9cb4ea80a7ceb3748062c30aa7ac8dee928f20374a9b53c`。manifest：`patch-files.json`，origin：`patch-origin.json`。详细日志：`regression-before.log`、`regression-alias-before.log`、`regression-alias-after.log`、`qualification-suite-final.log`、`final-ruff.json`。独立审查：`reader-independent-review.json`。

## #2969 的新真实 Reader 托管执行

Reader 修复已由 root 推送为 #2969，source `ca2768978429a2c9a98641fa2d58a8f587b88874`，tree `9f208412f8b8457df764b3b7026869f4e4718103`。独立读取 [run 39524743076](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/39524743076) 以及 job `118976636455` 的代码、日志和实际 artifact；该 run attempt1 成功，模型 evaluator 在 01:02:45—01:03:58 UTC 执行。不能仅凭 job green 推断模型调用；这里用实际 report 的64行、summary、runtime收据和精确源码共同验证。

Artifact `12312374935` 为58,501 bytes，SHA256 `beb82b997808c7e2d158fa51d711fb04259069480c891f16a67f8627bce5210d`，与GitHub提供摘要一致。包含三份非权重JSON：report、summary、runtime compatibility receipt。模型为 `convaiinnovations/laya`，固定 revision `c5d78730f3493e4fe16d61507ef4b78eef7318cf`，观察到的完整checkpoint目录指纹 `94fe55dd163eedcb9b0c3e167e4afe87ab13cc8daf39b299f880ada2860e5d5a`。运行使用 Python3.12.3、torch2.11.0+cpu、transformers4.57.6、laya0.3.20，以及记录前后SHA的CuTeDSL类型注解兼容修补。

实存调用数 **64 = 16个注册任务 × 四臂 × 1次答案顺序呈现**。report、summary和expected count完全一致，64个(task,arm,presentation)键无重复或缺漏。固定数据manifest SHA256 `eb869c45c77db4e85bf9e6013aa62925c3981d804c1709d0b2bb4a6e9a1edc89`，来源为先前主库 `f8c9419df6ddeb36ff8b522a50219981fb8d9345` 的六份仓库文件。本轮逐份从当前ca276源码获取，Git blob、支持与withheld引文行均匹配。registered evaluator源码实际调用 `laya.load(..., device="cpu")`，每条件执行一次 `agent.predict`，load前后及收集后重算checkpoint fingerprint；它输出按任务排序的行，因此输出顺序不等于真实调用顺序。

| 臂 | gold正确 | evidence-condition正确 | 不受证据支持的断言 |
|---|---:|---:|---:|
| full | 16/16 | 16/16 | 0/16 |
| distractor | 5/16 | 6/16 | 10/16 |
| none | 7/16 | 2/16 | 14/16 |
| withheld | 9/16 | 2/16 | 14/16 |

本地只读 verifier 复算每行标签、选项旋转、请求字符数、源绑定和token<512约束，复算全部11个summary指标均一致。模型执行总wall为66.0581秒。这证明该固定Reader诊断实际运行；16个已有仓库任务不等于64个独立新样本，也不是Memory Qwen的九臂40＋72重跑。

运行日志包含 `RuntimeWarning`：checkpoint部分温度无效/越界，被clamp到0.5，SDK明确提示相关confidence未校准。report保留 `descriptive_not_statistically_qualified=true`、`production_selection_authority=false`，evidence_class为 `local_typed_reader_model_if_checkpoint_confirmed`。此次没有独立held-out校准或新来源隔离认证；只跑1次答案位置呈现，没有完整4位置counterbalance。输出未保存完整类别概率向量，故Brier aggregate重算只验证了已保留逐行分数的一致性；没有权重或逐文件checkpoint inventory，离线无法重算观察到的目录指纹。FLOPs、能耗、完整峰值内存和checkpoint/resource/calibration join仍未补齐。没有资格升级或生产授权。

详细审计：`reader-2969/independent-verification.json`。原审计目录已实际执行 `verify-artifact.py`，模型调用为0。本checkpoint保留其源码、结果、API元数据、exact-source workflow/evaluator/manifest和六份来源文件；ZIP及完整job日志的省略与恢复入口见 `RAW_OMISSIONS.json`，不能把选摘checkpoint当成原完整工作目录。

## 最终本地资源与真实推理边界

最终资源快照时间 `2026-10-21T01:31:57.090051+00:00`。剩余磁盘 **1,806,667,776 bytes**，已包含本轮 native target / cache 的占用；CPU=9，MemAvailable=5865048 kB，未发现 NVIDIA 设备，当前 Python 3.12.14 未安装 torch/transformers/accelerate/safetensors。固定 Qwen baseline 的历史模型文件为 **6,183,463,389 bytes**，仅 checkpoint 已超过剩余磁盘。详见 `local-model-resource-final.json`；最初 3.75GB 观察值只保留为历史快照，未作为永久资源结论。

本轮没有在本地下载替代模型或执行 Memory 新推理。若资源变化，需要重新检查同一固定模型、pin 的 runtime、峰值内存和完整输出保存；要升级科学证据，还需独立来源/留出注册、独立语义与引文审查、真实时间窗口及完整成本。托管 Reader64 的实际执行已单独核验，不能替代 Memory40+72。

## Rust native 实测与既有 fixture 修复

原 #2968 `f740aaef183e0c1724871189fe1d72fc5204a49d` 的真实 Memory 库测试为 **271 passed / 1 failed / 7 skipped**；严格 scoped Clippy exit0。失败是实际已迁移到1..15，但 V2 fixture 的硬编码历史仍只期待1..14。在精确未修改的 `0cb777545966333a96be265a69d03c9982231bc7` 上再作聚焦负控，1项测试仍失败，确认不是历史head代替当前缺陷。初次缺sysroot及工具会话中断的尝试各自保留；中断不带虚构终态或通过结果。

已核实并原样移植既有 owner [#2743](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/2743) 的两行修复，当前 head `4290ec6480944af84646e8846dfe5e3dc5e73f81`、完整新文件 blob `dc6ae36263e1aab8c5c83e13649892ae9d3112c2`：在 group_concat 的输入子查询内排序，并硬编码要求1..15。所有 Memory 保存、引用、legacy header 和四张 KG 投影撤销断言原样保留，未修改生产迁移或权限策略。独立审查确认该文件与既有 owner blob 完全一致。

最终测试对象为 exact prospective combined source **`6b074e52621d77338112f02119beb0cb1a6f869f` / tree `cc6170562020d8271196cbdf9d0e71fde7955ded`**，加两行fixture及两份经CI代理实际生成/核验的TLS锁。测试时是本地未提交 candidate，不能把记录写成某个尚未发布commit已通过。全部工作区diff SHA256为 `99ba4b1d81447b477e44bf414f8da398739746f74b591c3e30a8b31385a232a1`；Cargo.lock SHA256为 `aa3efcad4d26d4ba8d5b8adbea793955acef36551f00da43ef7b03bbab3bfb5a`，MODULE.bazel.lock 为 `394f5d9cdcc1d9c96cebc357ad4635a01f0fa80f2e76a4d6665989343352f3ea`。

| 最终组合执行 | 真实结果 |
|---|---|
| `just test -p codex-hepta-memory --lib --locked` | 272 passed / 0 failed / 7 skipped，exit0 |
| `just test -p codex-utils-cargo-bin --locked` | 2 passed / 0 failed / 0 skipped，exit0 |
| `just clippy -p codex-hepta-memory --locked -- ...` | exit0 |
| `just clippy -p codex-utils-cargo-bin --locked -- ...` | exit0 |
| 收尾 `just fmt` 与 `git diff --check` | 均exit0，三文件字节完全未变 |

Clippy 使用 `-D clippy::correctness -D clippy::await_holding_lock -D clippy::await_holding_invalid_type -D clippy::expect_used -D clippy::unwrap_used`，保留仓库配置；未声称所有warning为零。源码与锁在每项执行期间保持一致。按 AGENTS 要求，fmt后没有重跑测试。记录位于 `native/final-validation-summary.json`、各命令的 `*-result.json` 和完整日志。

七项跳过均来自仓库既有 `#[ignore]`，涉及 KG容量、子进程崩溃/重开、target-host观测、1000次SQLite/kill-replay压力资格；本轮未解除忽略，因此这些资格尚未由本轮272项测试认证。该范围也不等于全workspace、Windows/macOS/Bazel完整构建、性能或生产验收。磁盘曾在并行构建时报告可用0，本轮最终命令仍真实成功；未把预警伪称为发生了ENOSPC测试失败。最终可用空间已重新实测。

## Checkpoint 阅读范围

本目录是紧凑证据checkpoint，文件名以 MANIFEST.json 为准；原工作目录命令和绝对cwd仅记录实际执行上下文。raw归档/日志/完整源码省略清单和可恢复的GitHub入口在 RAW_OMISSIONS.json，不能直接将原工作目录命令当作本目录自包含运行入口。

`reader-2969/source/` 的六份文件是为 blob 与引文核验保留的原始字节片段，内部相对链接仍属于固定源码 `ca2768978429a2c9a98641fa2d58a8f587b88874` 的仓库上下文；它们不是完整文档站。请在对应 GitHub commit 的完整仓库路径查看这些引用。没有为改善导航而改写 pinned source。
