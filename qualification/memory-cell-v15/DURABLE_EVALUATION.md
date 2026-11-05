# Durable prospective evaluation

Status: scoped research implementation; `production_authority` remains `false`.
The existing `MatchedEvaluator` stays diagnostic. Use this wrapper when a result
must carry a durable reservation; older unreserved reports do not acquire one.

## API

```python
from durable_admission import DurableMatchedEvaluator
from experiment_ledger import ExperimentLedger

ledger = ExperimentLedger("/persistent-owner/evaluation.sqlite")
runner = DurableMatchedEvaluator(
    evaluator, ledger, "experiment-id", loader_source_runtime_sha256,
    runs=(candidate, incumbent),  # Supply every registered arm, not just this pair.
)
receipt = runner.evaluate(
    "stable-operation-id", candidate, incumbent, candidate_cost, incumbent_cost,
    manifest=manifest,
)
# receipt["state"]; receipt["result"] exists after durable completion.
ledger.close()
```

The execution identity is a trusted 64-character SHA-256 identity for the loader,
source and runtime. Callbacks for the whole registered roster and the common
executor freeze before any comparison dispatch, including initially unused arms.
The persistent family binds these snapshots, registration, cases, protocol,
implementation hashes, comparison roster and planned-look bound across restarts.
Each request also binds the exact comparison, look, cost receipts and manifest.

## Reservation and recovery

SQLite WAL, `synchronous=FULL` and `BEGIN IMMEDIATE` serialize one persistent owner.
One comparison/look slot grants one private dispatch token. Reservation and
`running` commit before predictor/executor dispatch; the complete result commits
before return. Exact duplicate requests return the retained envelope without a
new token. Reusing an operation ID with different content rejects.
A crash leaves `reserved` or `running`; reopening does not steal an active worker.
`retain(operation, "unknown" | "cancelled", reason)` records an unresolved outcome
without releasing its slot. It neither kills a worker nor proves its effects ended.
No automatic replay, timeout-based reassignment or late terminal overwrite exists.

## Trust, provenance and costs

Every cooperating process must use the same owner/database on a filesystem with
SQLite locking and durability semantics. A new database, whole-authority rollback,
file replacement or administrator tampering is outside this guarantee; restoring
an old database does not establish that its consumed slots are fresh.
Source-unit and cluster claims are global to this owner, so ingestion must supply
stable, trusted, namespaced provenance IDs. Unnamespaced ID collisions can cause
conservative rejection. Exact public-input claims also reject reuse after simple
ID renaming; semantic variants still require trusted lineage checks.
Trusted host callbacks are serialized and reconstructed before reservation; this
can execute setup. The dispatch guarantee covers predictor/executor invocation.
Setup, serialization, snapshots and ledger I/O belong in complete cost accounting
and are not automatically measured by the inner workers. Imported libraries,
external model files/services and honest provenance remain the loader's boundary.

## Evidence and limits

Focused tests passed **20/20** normally and with `-O`; raw logs, commands, exit codes
and source hashes are in [retained evidence](evidence/durable-evaluation-20261105/).
Positive controls cover real isolated evaluator dispatch and cached completed
receipts. Negative controls cover eight-process contention, abrupt exit at three
phases, changed requests, forged tokens, source reuse, unknown/cancelled retention,
look-2 callback replacement and adapting an unused arm after an earlier result.
The independently discovered `True == 1` output-scoring defect belongs to the
separate typed-output repair and its tests; durable reservations alone do not fix it.
These synthetic controls establish protocol behavior, not real-model accuracy,
long-term benefit, full measured costs, distributed production authority or a
profitable Meta Network. Integrated source qualification is recorded separately.

## Current user request (verbatim)

```text
全量冲请研究 Hepta Neuron 如何分化成不同类型的 Memory Cell，使小模型在单节点专门压缩、存储、检索并更新某类记忆，再通过 split/merge、跨节点路由和持久迁移组成 Meta Network；明确该方案与 MoE 的专家专用性、路由、共享状态和权限的相同与不同，以及小设备获得大规模能力的真正条件。比较共享 Encoder + 专属 Head、KV/retrieval、ridge/centroid、Transformer/LoRA 参数记忆、类型化记忆和候选覆盖/专家内评分/跨专家路由。

实现可回滚的模型及记忆版本、唯一 owner、跨节点身份与证据、故障恢复和负迁移拒绝；对相同输入记忆、同预算、同执行器与完整存储/推理/训练成本评估准确率、长期稳定性和净收益。不得因参数化记忆更复杂或 Meta Network 节点数增加就推断整体智能或产品收益已提升。全量冲剩余blocker，直到所有blocker全部闭合
```
