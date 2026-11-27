# Public boundary-program extension: prepared, not executed

This directory adds a separately counted eight-forward experiment to the fixed
seed-47 sender40 pilot. It is an adaptation of WeightCode's idea of a program
that measures a particular parent and constructs its edits. It is not a rerun
of the paper's ViT benchmark, an unseen-task evaluation, or a production model
transaction. The original v4 mathematical source and target protocol are copied
without edits and checked against their frozen SHA256 values at entry.

The new proposal targets the actual sender boundary, whose message enters the
receivers. It solves the coupled equation in which both drift and cost depend
on the same preactivation. This differs from the predecessor's inverse of an
average drift. There is no assumption of global monotonicity. The frozen
interval procedure must classify the whole z domain and certify exactly one
root for every required target. A second root, uncertain sign, unreachable
target, root/partition limit or time limit produces ABSTAIN. No failed target
is removed, clamped, or substituted. Real-surrogate roots do not assert exact
attainment by the F32 recurrent rollout.

## Fixed input and parameter scope

Only the original public checkpoint, public raw task caches and original public
Hybrid/SmallHCSN code are allowed. The new public PT identity is explicitly
mapped to the already-reviewed per-tensor identities in `IDENTITY_AMENDMENT.json`.
The earlier canonical Safetensors identity is historical provenance only; that
file and private feature caches are not inputs to this lane. The 40 editable
F32 values remain the 4-by-9 sender input-drive matrix and its four biases. All
other registered tensor/buffer bytes and readout aliases stay fixed. A new
Torch serialization is not claimed to preserve the parent's ZIP/header bytes.
Every candidate is evaluated after loading and verifying its actual saved
complete checkpoint with the predecessor's qualified helper.

The actual source trace must come from the sole completed, qualified public
sender40 run. Its archive, selected files, actual original source paths, parent,
normalizer, labels, query/gallery/actor identities and helper hashes are bound.
`prepare_evidence.py` selects only declared plain files from that exact archive;
it neither executes an archived script nor fetches a substitute artifact.
Preparation and model execution are separate.

`INPUT_BINDINGS.template.json` is deliberately not executable. Root must bind
the real predecessor run ID, artifact ID, archive SHA/size, source head and
selected file SHA/size, then record the final independent review SHA before
changing status to `FROZEN_FOR_EXECUTION_AFTER_ROOT_REVIEW`. These bindings may
be filled without changing mathematics, parent, doses, selection, or budgets.
No input identity is guessed from a successful-looking filename.

## Operation order and honest costs

The runner checks only predecessor completion/source/qualification facts before
construction. Training trace and parent-correct labels are the sole source of
targets. It constructs all four declared directions and candidate checkpoints,
then seals the exact bytes before decoding the saved held baseline scores or
using any predecessor candidate quality for comparisons. All new candidate
development/retention forwards are after that seal. Original task data is
loaded by the predecessor helper, but dev/retain labels do not enter fitting.

The four fixed candidates are boundary doses0.25 and1, a wrong-role dose1, and a
seed20261129 Gaussian control. The Gaussian direction has the same continuous
support and norm as the full boundary direction; actual F32 realization can
change their relative norms. Both exact squared norms and their difference are
reported. Wrong-role and random outcomes cannot enter method selection.

The incremental budget is eight original full six-tick rollouts: four train80
and four combined dev32/retain28. That is48 body ticks,560 paired-query rollouts,
zero backwards and zero optimizer updates. The two shared10-by-4 fits, every
scalar root call, visited interval, bisection and point/interval equation call
are separate counters. Each inverse gets a durable result, including partial
evidence when it rejects. The three slow ticks of each train candidate also
perform12 explicitly budgeted linear recurrences to recover the real z. Dev
calls do not replay them. These are not extra full model rollouts, and their
time is not free.

The actual z is compared to a clearly labelled F64 frozen-state surrogate
`z_old + K * actual_F32_parameter_delta`; this discrepancy includes F32
arithmetic and recurrent-state effects. No shadow complete rollout is used.
The reported boundary error is the actual boundary minus the fixed target, not
an extra uncounted evaluation of the scalar residual at every trace row.
Receiver FirstPassage risk and value changes are measured from the original
full-model trace alongside task quality. Physical improvement is not treated
as proof of task or NDU improvement.

The predecessor33F/17B/16updates and all shared qualification/trace costs remain
separate and are reported as already incurred work. A completed comparison
would therefore contain41F and17B; only the incremental boundary method has
zero parameter backwards. The common data and fixed40-coordinate scope do not
make the physical surrogate and task-loss BP the same objective. No speedup
or equal-quality claim follows simply from counting zero new gradients.
This conversation's editing/token cost is unavailable, not measured zero.

## Runtime boundary

`supervise.py` requires an independent Linux cgroup with at most1GiB, one CPU
and64 tasks. It starts one child, pins one available CPU, enforces120 aggregate
CPU seconds and180 wall seconds with0.2-second sampling, and keeps the child's
RLIMIT_CPU120/121 as an outer backstop. The reviewed service launch must add
`RuntimeMaxSec=210` and `KillMode=control-group`. It records one owned PID before
monitoring and does not retry, migrate to another machine, or relax limits.
Model forward calls retain the original20-second return-accounting gate; that
gate is not atomic preemption. If a process is killed, the last complete ledger
entry and partial artifacts are preserved.

Prepared invocation after root review and exact evidence preparation:

```text
prepare_evidence.py EXECUTION_BINDINGS.json EXACT_PREDECESSOR.zip NEW_EVIDENCE_DIR
supervise.py EXECUTION_BINDINGS.json PINNED_PILOT_HELPER_DIR PUBLIC_PREPARED_DIR NEW_EVIDENCE_DIR NEW_OUTPUT_DIR
```

The unchanged original `prepare_public.py` must first create `PUBLIC_PREPARED_DIR`
from its fixed public URLs, with its required separate preparation-result path.
The helper directory must be the exact reviewed predecessor code. Dependency
setup/download and archive preparation costs are reported separately. The
workflow template remains disabled until source/artifact/review identities are
filled. It must never rerun the predecessor to obtain missing evidence.

The separately registered83/137 rerun-versus-copy phase remains unexecuted and
is not part of this runner. Its66F/34B/32updates are unchanged. Historically
seen train/dev/retain data can support across-parent stability observations,
not a fresh heldout or financial-return claim.
