# Hepta Shared-Stem Group: Evidence-Step Curriculum, Paired Costs and Admission

Date: 2026-10-15. **Research only / DRAFT / SHADOW / DENY_ALL**.

## Why this child exists

The completed three-seed pretrained Granite97 campaign in #2271 is a negative
capability result: on 288 ordinary eight-way cases, static got 31 correct,
recurrent/NDU 26, and the split candidate 31 while costing more CPU. No Cell
split was selected, no natural future reasoning emergence demonstrated. A
verifier-guided recurrent Group trained only on terminal class does not thereby
learn evidence traversal, constraint updates or temporal state transitions.

This child preserves #2271 source and adds two different gates:

* **TRAIN-only intermediate evidence supervision:** derive source-bound,
  target-independent public operations, align each selected evidence fact to
  offset-aware frozen Granite token rows, supervise the existing Core's attention
  *during training only*. Old `Core.step` and product Neuron V1 requests still
  return their original values; inference has no teacher callback or label access.
* **Source-group paired utility diagnostics:** an independent standard-library
  reviewer rechecks source/evaluator identity, complete cohort×arm membership,
  fully registered normalized eight-phase costs, unsupported-evidence denials,
  rescues/harm and per-cohort retention. A favorable bound can only be diagnostic
  while independent source-group sampling and execution are unauthenticated.

## Paired campaign

`group_attention_campaign.py` loads the exact frozen Granite97 revision and
uses one feature producer/cache. It fits four independent models on identical
TRAIN source membership:

| Arm | Comparison purpose |
| --- | --- |
| `static` | Cheap no-recurrence baseline |
| `wide` | Approximately parameter-matched static reference |
| `core` | Original four-step recurrent model |
| `attention` | Identical Core initialization + same SGD sampler + teacher masks |
| `core_fixed`, `attention_fixed` | Actually run the existing four-round propose/verify/value/revise loop using each frozen model |
| `core_ndu`, `attention_ndu` | Actually invoke the existing bounded continuation controller; verify episode stop reason and physical search work |

The last two have **the same trainable parameter count, training rows, SGD
updates and sampled depth/indices**, independently checked by a receipt digest.
They do **not** have equal training arithmetic, because the attention arm pays
for auxiliary loss and tokenizer offset binding.
The inference comparison now also includes **two individually frozen critics**,
fitted only on non-overlapping halves of a distinct `validation` source
partition; this critic preparation, training and calibration are additional
measured CPU/wall cost. The `fixed` and `ndu` arms run the actual existing
`execute_group` callbacks and record workspace steps, verifier calls,
terminal status and search formula work. The standard-library replay must
reject impossible verifier-accepted statuses, stale model/feature hashes,
missing execution work, wrong critic source groups and inconsistent
`fixed` depth. Its printed paired rescue/harm and costs are descriptive, not
causal or matched total-compute acceptance.
 Exact physical CPU and wall
measurements, train operator ledger, feature cache resident bytes, Encoder
forward counts, and teacher-generation costs are separately retained.

Test panels include ordinary, deeper unseen chain lengths, deleted premise
and untrained source-composition. The latter reuses component test evidence
and is not independent in a causal source-publisher sense. Deleted-premise
answers always count as unsupported attempts, not correctness by coincidence.
No output is selected from TEST. The paired standard-library review re-derives
all public symbolic answers and rejects malformed source identities, missing
rows, fabricated recorded correct flags, changed frozen model hashes, training
schedule drift, missing observed cost, stale teacher binding or altered
evidence. It does not independently attest CPU/GPU hardware or model execution.

## Reproduction

For local source and CPU regressions when PyTorch and dependencies are already
installed:

```sh
PYTHONPATH=qualification/stem-cell-v1 python -m unittest \
  test_group_step_supervision test_group_attention_curriculum \
  test_group_training_attention test_group_attention_campaign_review \
  test_group_independent_utility_gate -v
```

With the pinned public checkpoint downloaded only by the explicit acquisition
command, a full real-model single-seed run is:

```sh
python qualification/stem-cell-v1/group_attention_campaign.py \
  --acquire --snapshot /tmp/hepta-granite-step \
  --output /tmp/hepta-group-paired --seed 41
python -S qualification/stem-cell-v1/group_attention_campaign_review.py \
  /tmp/hepta-group-paired \
  --output /tmp/hepta-group-paired/independent-review.json
```

The separate hosted workflow
`.github/workflows/hepta-group-attention-curriculum.yml` requests real
three-seed CPU campaigns (41/47/53) only after CPU regressions. A queued,
cancelled, skipped, or locally unexecuted experiment is never a PASS. Archive
actual logs and exact SHA/source receipts before making numerical claims.

## What this does not grant

No real multimodal image/audio/video skill is introduced here; no decoder is
trained. No observed System 2/NDU winner, certified FBSDE global solution,
4,096-Cell physical forward claim, FastCell executable-memory authority,
native product ABI change, or automatic model promotion is authorized.
The trained Group must beat static and unsupervised recurrence on **complete
future task outcomes at matched total compute and independent sources**,
including reliability under missing evidence and old-task retention, before
consideration for a selected runtime. Inference-time teacher use and
evaluator/selection label access are prohibited.

## Strict independent JSON / archive admission hardening

The latest research-only independent reviewer rejects duplicate JSON keys, NaN/Infinity (including overflowing exponent notation), oversized records, symlinked input files, and ambiguous safetensors headers before any hash or success comparison. This is a bounded structural negative control; canonical hashes and local checks are **not** independent model-execution or CI attestation.

## Frozen optimizer-family research comparator

The real pretrained workload now executes two **predeclared regimes** on each of seeds 41/47/53:
\`sgd_v1\` (SGD without momentum, Core learning rate 0.05) and \`adam_v1\`
(unfused/non-foreach Adam, Core learning rate 0.008). Both preserve identical
public datasets, same initial Core bytes and 120 SGD/Adam optimizer steps,
but not identical arithmetic, optimizer memory or learning rate. Cheap static
arms still use the original SGD. Every fit reports actual optimizer-state
bytes, live work ledger, sample/depth digest, trained-weight bytes and both
CPU/wall cost. The independent stdlib reviewer checks the sealed profile
and rejects parameter/state/schedule mismatch. These are **training-regime
comparisons**, not a proof of a pure optimizer causal effect. No winner
may be selected from test outcomes; no natural task, independent future
source, matched-total-compute or production claim is made.

A separate local CPU **synthetic mechanism** toy (not the pinned Granite97
campaign) showed severe SGD underfitting and rapid Adam convergence across
three seeds. That finding motivates this controlled experiment but does not
rank real Stem candidates or qualify a deployed Cell.

## Independently paired SGD/Adam execution diagnostics

When all six physical research jobs complete, a final GitHub Actions job
downloads artifacts from the **same run** and performs a stdlib-only cross-run
audit. Both original case, callback, source and model-byte reviews must pass.
The reviewer requires the same source material, frozen input inventory,
initial Core and SGD/Adam sampling schedule; it reports paired rescues/harm
and separately observed training, Encoder, teacher, Critic, online and
checkpoint costs. It deliberately does **not** certify equal compute,
same physical host, prospective independent cases, or any optimizer winner.
The research output remains DENY_ALL.

## Full per-step proposal and verifier semantics (research V2)

The research-only System2 trace V2 now stores the bounded actual A–H candidate sequence. A separate stdlib module recomputes proposer and verifier output digests from each public symbolic fact, validates fixed-depth forced rejection, checks NDU continuation estimate hashes and terminal reasons, and rejects rehashed false candidates. This verifies semantic internal consistency only; it does not attest external model execution, task source authenticity or real-world reasoning efficacy. Production remains DENY_ALL.

## No silent truncation of terminal evidence

The original TRAIN-only attention curriculum used `steps[:max_depth]`, which
silently omitted the terminal `read_terminal_label` for a legal four-edge
dependency path (five necessary operations versus four recurrent steps).
The research V2 curriculum now packs **all** canonical public operations into
up to four ordered attention stages; multi-operation stages share token masks,
and the final terminal evidence always remains included. The receipt records
`coalesced_teacher_steps`, `supervised_slots`,
`terminal_evidence_supervised_cases` and a source-bound slot mapping digest.
Both individual and cross-optimizer reviewers deny truncated evidence or
divergent attention slot identities. Packing operations does **not** prove
that the learned recurrent Core can execute each logical operation; downstream
heldout accuracy and work must still demonstrate that ability.

## Independent public-source operation/slot replay

The compact V2 teacher manifest now archives the actual TRAIN-only
operation type, public fact row, source group, and compressed attention slot
for every operation. A separate **standard-library-only** reviewer
reconstructs dependency reachability, constraint row sequence, and temporal
latest-event updates from the publicly persisted source text (not imported
training labels or the original `group_step_supervision.py`). It independently
checks every recorded slot, original source digest, required terminal
evidence, total operation count and coalescing count; even a forged
`slot_assignment_sha256` that was recomputed after dropping or shifting
the terminal record is rejected. This is semantic evidence continuity only,
not an independent physical tokenization or model-execution attestation.

## Exact frozen-forward Token-ID binding

Research teacher retokenization now checks original integer input IDs, not merely aligned length and attention masks. The frozen Encoder records a source/scope/generation-bound SHA-256 for each successful actual forward; the TRAIN teacher must reproduce the same digest using the offset-aware tokenizer. The campaign keeps an ordered TRAIN token witness inventory and the independent and cross-optimizer auditors deny missing or changed same-shape Token IDs. Legacy independent teacher callsites without a witness are explicitly marked unbound and cannot pass the full campaign review. This is consistency of real input bytes within one study, **not independently attested remote execution**.

## Operation-level Attention coverage rather than union-only mass

The previous auxiliary loss minimized only `-log(P(any selected evidence token))` for each recurrence. On packed stages with 2+ mandatory evidence operations, this can be nearly zero while entirely ignoring one required operation. The updated TRAIN-only teacher optionally emits a bounded four-dimensional per-operation mask (`case × depth × operation × tokens`) whose union exactly matches the existing V2 evidence mask. The measured research attention arm uses `mean_per_operation[-log(P(each required fact))]`, not union-only mass, with unchanged base Model/Core and no inference-time teacher. Old direct callers retain the original return signature; campaign acceptance explicitly requires the operation loss contract, actual per-operation tensor digest, memory bytes and consistent SGD/Adam teaching material. Extra mask preparation, forward/backward arithmetic and optimizer resources remain charged in actual lifecycle; this is a testable supervision intervention **not** a claimed reasoning capability gain.
