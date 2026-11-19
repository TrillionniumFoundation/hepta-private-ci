# Trainable Cell implementation routes

This package implements two trainable producer routes and one shared experimental
owner. It reuses the existing native compatibility-bundle format and the PRED-1
GRU/diagonal recurrence; it does not replace the native daemon's state owner.

| Route | Executed implementation | Local learning | Persistent state |
| --- | --- | --- | --- |
| A: shared semantic features | One registered LLM/VLM feature provider per complete frozen binding, optional frozen domain projection, private linear or low-rank head | MSE or cross-entropy on the private head; returns an immutable candidate | Owner-managed state, view, quota and request receipts |
| B: stateful temporal kernel | GRU by default; simple diagonal SSM control | Original PRED-1 BPTT/Adam on complete episodes; returns independent parameters and optimizer state | Owner/config/weights/episode/cursor-bound hidden state |
| Deterministic components | Exact retrieval, finite rule grammar, numerical algorithms, injected host tool capability | No neural training | Same state owner, replay and recovery interface |

The diagonal SSM is not S4D or Mamba. HCSN is an explicitly unadmitted research
candidate in this producer registry. Its separate formal protocol
belongs to the HCSN branch; the source of truth for this change is the immutable
[5f7f55e0 protocol](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/5f7f55e015dde7fab0c174081fef090ff45501de/proposals/localization-v2/formal_protocol.json).
This package does not start or relabel those formal fits.

## Entry points

All components expose `identity`, `initial_state()` and
`step(payload, state, context) -> StepResult`. `CellOwner` supplies the explicit
principal/agent/cell/run partition, retrieval view and budget. `SemanticComponent`
and `TemporalComponent` bind their actual parameters/configuration to a complete
`Bundle`. Deterministic implementations additionally bind their actual corpus,
rules, operation or tool descriptor into their identities.

```python
from hepta_cells.bundle import Bundle
from hepta_cells.lifecycle import Budget, CellOwner, Partition
from hepta_cells.temporal import TemporalConfig, TemporalKernel
from hepta_cells.temporal_component import TemporalComponent

kernel = TemporalKernel("prediction", TemporalConfig(3, 1, 2))
# components is the host's complete frozen CellBundleComponentsV1 mapping.
components.update(base=kernel.kernel_sha256, heads=kernel.heads_sha256,
                  composition=kernel.config.sha256)
bundle = Bundle("artifact:prediction", 1, components)
component = TemporalComponent(kernel, bundle, "run:one")
partition = Partition("principal:one", "agent:one", "prediction", "run:one")
owner = CellOwner("cells.sqlite")
owner.create(partition, component, budget=Budget())  # once, not on every restart
receipt = owner.step(partition, component, "observation:one", {
    "operation": "observe", "cursor": 0, "observation": [1, 0, 1],
})
owner.close()
```

Reopen the existing database to resume. Reuse the exact original request after
acknowledgement loss. A pending request never authorizes another invocation.
Host readback must identify the original outcome and original execution cost;
unknown cost remains unknown. External effects that completed over budget retain
their resulting state and require explicit recovery before subsequent work.

The owner epoch is distinct from the native bundle generation. Local restore or
rollback never refunds spent work or re-executes old requests. Native rollback
still needs a new lineage-bound bundle generation and the native owner's cutover.

## Seven-lineage populations

[`POPULATION.md`](POPULATION.md) describes the frozen `PopulationPlan` and its
integration with this same owner. Supply `population=plan` when creating a new
owner, then create each partition with its specification's exact budgets. The
plan binds all seven responsibilities to implemented component classes and limits
local plasticity to two logical Cells by default, with an explicit maximum of
three. The initial allocation opens MEM private heads and the PRED GRU while
retaining frozen components for the other responsibilities.

Reopening the database without a plan still enforces its retained policy.
Subsequent runs load the current admitted logical-Cell version with independent
state. Candidate adoption checks its frozen local scope and unused committed
observations as well as the existing host qualification. These are experimental
composition and recovery contracts; task competence requires separate evaluation.

## Learning and version adoption

`SharedSemanticPool.train_candidate` trains only the private head. Both factors
of a low-rank head are trainable; the optional domain projection remains frozen.
`TemporalKernel.train_candidate` clones the parent parameters and Adam moments.
It consumes complete past-only episode batches with fresh hidden state, preserving
the parent serving kernel. A new parameter digest rejects the old hidden state.

`bundle.py` produces the exact `CellCompatibilityBundleV1` byte encoding. The
native `validate_cell_local_update_v1` and Python `validate_local_update` enforce
the same declared local-update scope:

- A: heads, or explicitly declared Cell adapter plus heads.
- B: recurrent kernel/base plus heads.
- Encoder, tokenizer, domain adapter, composition, numeric profile, output schema
  and state semantics remain fixed for these local updates.
- The candidate must be the immediate lineage-bound next generation.

The host must obtain the family and trainable scope from its frozen definition;
a candidate cannot supply its own wider policy. These producer-side checks compare
commitments, not arbitrary tensor semantics or authenticated evaluation evidence.
`prepare_cell_local_reset_v1` builds the existing native sealed Reset plan;
publication/readback remains with the existing owner. An explicit host evaluation
callback is required for experimental `CellOwner.adopt`, and omission rejects.

## Costs and serving

The pool batches only compatible base/model/encoder/tokenizer/numeric/domain
bindings. Per-Cell and aggregate input/item/array limits apply before dispatch.
Provider failures retain charged attempts. Shared host arrays are counted once;
private head arrays are counted per Cell. Array bytes are not process RSS or VRAM.
Provider-side allocation and preemptive time limits remain host responsibilities.

Temporal work units are parameter-count proxies for one streamed step, not FLOPs
or energy. Training receipts contain measured local wall/process CPU time,
updates, datasets, parameter identities and failures. Unmeasured energy and peak
RAM/VRAM remain null. Shared-base GPU memory and latency require an actual serving
run; they cannot be inferred from the NumPy unit fixtures.

The optional `MLXLlamaFeatureProvider` supplies a real, frozen Llama hidden-feature
path on Apple Silicon: every transformer layer and final RMSNorm execute, then
the final valid token is pooled. It accepts an independently downloaded, pinned,
checksum-verified local artifact set. The provider serializes access, limits text,
token and batch sizes, and records actual MLX allocator counters separately from
process RSS and host-array accounting. Its MLX memory setting is a guideline, not
a strict operating-system memory limit. Full parameter fingerprints are checked
around each encode, and their cost is retained separately from forward latency.

`qualify_hepta_semantic_serving.py` compares four separate Cell requests with one
compatible batch using the same loaded model, then trains four private candidate
heads. It preserves raw features, nonzero logits, candidate arrays, complete
bundles, failures and source identities. This is an optional serving measurement,
not a language-quality evaluation or a comparison against four resident models.

## Reproduction

```sh
python3 -m pip install -r scripts/hepta_cells/requirements.txt
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 \
  python3 -m unittest discover -s scripts -p 'test_hepta_cells_*.py' -v
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 \
  python3 scripts/qualify_hepta_cells.py --output /absolute/new/attempt-directory
```

The probe freezes protocol and source hashes before execution, preserves all
seed-level results and failures, and refuses to overwrite an earlier attempt.
It checks real local gradients, checkpoint/optimizer recovery and next-task
consumption through a real SQLite owner. The exact first-cue rule is retained as
a control. High scores on this small synthetic probe do not establish a
real-task advantage over rules, retrieval, stronger trained temporal baselines
or a production readiness gate.

The original PRED-1 files are copied without changing their bytes from commit
`3959aac6829a345ef674b7901cbdd62316305d89`. Engineering evidence and source identities
are recorded in `qualification/stem-cell-routes-20261108`.
