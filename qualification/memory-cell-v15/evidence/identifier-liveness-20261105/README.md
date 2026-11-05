# Reject malformed identifiers before freezing a Cell

Base: `f88b826d3c22b5f89fd350dab4813be2855a2f93` (#4885). This is a
reference-protocol liveness correction and a matching native transition boundary.
It does not activate a production lifecycle owner.

## Reproduced failure and repair

The same `probe.py` issues real signed requests against a disposable SQLite
authority. On the pinned base, `prepare(transfer=null)` succeeds and stores a NULL
TEXT primary key. The cell advances to `prepared/epoch=2`, but ready/commit/abort
cannot find that transfer; admin recovery also refuses the frozen cell.

The repaired implementation rejects before mutation. The probe then completes a
normal prepare → ready → commit, ending at `active/epoch=3` with the new owner.
`red.json` and `green.json` preserve both executions. Root independently replayed
the same source-pinned probe and observed the same two behaviors.

Cell identifiers are exact, non-normalized UTF-8 strings of 1–256 bytes; transfer
identifiers use 1–128 bytes. All related public operations, including reshape
parents/children, validate before writes. Opening an existing database scans the
persisted identifier columns and refuses malformed state with `recovery required`.
It does not delete transfers or silently reset the owner. Repairing an already
poisoned production database still needs a separately reviewed recovery operation.

## Executed checks

- Seven new Python cases exercise malformed values, all affected entrypoints,
  legal Unicode boundaries, cold reopen and reachable terminal transitions.
- Existing authority/counter plus new identifier tests: 33/33 normal and 33/33
  with Python assertions disabled, using the pinned existing Python dependencies.
- x230, Rust 1.95.0: three new native tests passed; format and `-Dwarnings`
  compilation passed; the original 64×24-operation differential fixture still
  matches all 1,600 output lines. Actual executed source hashes match the candidate.
- A first default-Python discovery attempt failed with seven missing-cloudpickle
  import errors. Its original log remains in the raw archive; it is not a pass.
- The partial authoring workspace cannot run repository `just fmt`: `just` and
  the full `codex-rs` checkout are absent. Scoped native formatting was actually
  executed on x230. Whole-repository CI is a separate, unqualified gate.

`QUALIFICATION.json` records exact source identities and the real durable job ID.
`raw-execution.tar.gz` contains the original logs, native input/output, full Python
oracle trace, remote command, process status and execution steps. The archive's
member hashes are in `raw-manifest.json`. Paths named by the qualification receipt
refer to these archive members when they are not separately published.

Reproduce the behavior with the same probe against each pinned source directory:

```sh
python qualification/memory-cell-v15/evidence/identifier-liveness-20261105/probe.py \
  qualification/memory-cell-v15
```

The scoped workflow now executes the new native identifier cases as well as the
original differential protocol. A queued workflow does not qualify this source.

## Original task

> 全量冲请研究 Hepta Neuron 如何分化成不同类型的 Memory Cell，使小模型在单节点专门压缩、存储、检索并更新某类记忆，再通过 split/merge、跨节点路由和持久迁移组成 Meta Network；明确该方案与 MoE 的专家专用性、路由、共享状态和权限的相同与不同，以及小设备获得大规模能力的真正条件。比较共享 Encoder + 专属 Head、KV/retrieval、ridge/centroid、Transformer/LoRA 参数记忆、类型化记忆和候选覆盖/专家内评分/跨专家路由。
>
> 实现可回滚的模型及记忆版本、唯一 owner、跨节点身份与证据、故障恢复和负迁移拒绝；对相同输入记忆、同预算、同执行器与完整存储/推理/训练成本评估准确率、长期稳定性和净收益。不得因参数化记忆更复杂或 Meta Network 节点数增加就推断整体智能或产品收益已提升。全量冲剩余blocker，直到所有blocker全部闭合
