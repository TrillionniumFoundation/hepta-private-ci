# Five causal experiments: execution and evidence contract

Date: 2026-10-13. Initial source base: `2b2dc655e5feb5224b9c3fe659e53c0768fdea7b`.
Reconciled concurrent dual-signature base: `d811dfb9c6499d7bbeb81c2772f0efab7974a644`.
Research branch: `research/five-causal-experiments-20261013`.
Related work: PR #1546 (existing System2/Reader research), PR #1682 (parallel
Stem/Head controls). No main merge, existing model replacement or production
permission is part of this change.

## Actual disposition

The five requested natural-task experiments are **not completed**. This change
implements a sequential, externally reviewed experiment execution/analysis
boundary and fixes a versioned Reader eligibility issue. It does not manufacture
a new cohort, human review, model weights, a model training result or a profiler.
No new real Encoder/Reader inference was performed during this change. Existing
native model/Head/Group/NDU/split implementations still need reviewed adapters
and provisioned checkpoints for the executor interface below.

Local execution is a **source-overlay** on Python 3.13.5, CPU-only PyTorch
2.10.0. The original `full_cell_matrix.py` and its tests were copied from the
completed artifact 11792286414 / run 38353948809. Its outer SHA256 is
`031e4a651e5bf398d2f5a30e307628a2c7fbb6d320d9f86cea731dff08997b0c`;
source blob `3c5e49dacb9e799e6c731774d52393898ab4636b` was checked against the
current repository file before editing. This is not a complete repository clone.
Full inherited research tests and target-host native measurements are separate.
The local runtime has no mounted model/cohort/review bundle, no GPU, no direct
connection to the existing project cloud, and GitHub/Hugging Face DNS calls
failed. The GitHub connector remains available for source reads and publication.

**Completed local tests:** the initial revision passed 52 new tests and 9 old
matrix tests. The reconciled revision passed 54 new tests and all 14 tests
from the concurrent dual-signature matrix revision. Fixture subprocess calls are not neural
calls. There are zero new natural-task scores, training gains or resource gains.

## Five groups, not a 768-way expansion

The registered protocol in `scripts/memory_cell/five_causal_experiments.py`
contains 22 arms and 15 prespecified paired contrasts:

| Experiment | Arms |
| --- | --- |
| Reader | no evidence; ordinary retrieval; independently reviewed sufficient evidence; exact critical-premise-group removal |
| Sharing | replicated full model; shared frozen Head; shared trained Head |
| Group System2 | stateless; independent attempts; fixed search; learned recurrent controller |
| NDU allocation | fixed budget; threshold rule; shuffled utility; NDU allocation |
| Multimodal/split | text only; joint unsplit; wrong pair; time shuffle; missing modality; offline split; fixed split |

A bundle can register only the current stage. Reader execution does not require
later-stage video assets to be installed. The five-group plan is retained; stages
are not expanded into every architecture combination. The full old matrix is
not deleted, relabelled or counted as executed.

## Reader v3: adequacy is not retrieval headroom

`hepta.reader-gate.v2` keeps its old byte/schema semantics, including its strict
ordinary-vs-sufficient gap. New independently reviewed `hepta.reader-gate.v3`
requires the same grounded sufficient-evidence and negative-control thresholds
but does **not** demand inferior ordinary retrieval. Ordinary retrieval that is
already as good as sufficient evidence is not evidence of a broken Reader.
The opportunity for improving retrieval is reported separately. Changing a
receipt's version breaks the existing review digest; v2 bytes cannot be silently
reinterpreted as v3. Out-of-band trust pins and capability restrictions remain. The concurrent
`d811dfb9` dual-Ed25519-signature and independently pinned reviewer-roster
requirements are retained in full for both versions. V3 signature messages
use ASCII `hepta.reader-gate.v3.ed25519`, NUL, then the 32-byte reviewed-content
digest; historical V2 signature bytes are unchanged. All signer keys in tests
are ephemeral fixture-only keys, never real reviewers or published private keys.

Malformed unhashable cohort entries now fail closed rather than throwing during
`set(cohort)`; boolean denominators are not accepted as integer observations.

## Material preparation and frozen bundle

No example natural dataset or fake reviewer key is supplied. An independent
curator must prepare a `hepta.five-causal.bundle.v1` with:

- the exact registered `protocol_sha256`;
- `data_kind=natural_unseen`; cohort records with `id`, `split`, `family`,
  `source_roots`, `exposure_groups` and original `content_sha256`;
- train/validation/confirmation/retention partition metadata, with source,
  content and exposure roots disjoint across partitions; confirmation task
  families disjoint from development; retention may reuse an old family but
  never the same source/content;
- matched trial records with `trial_id`, `experiment`, `arm`, `task_id`, exact
  public `request`, `bindings`, implementation/checkpoint SHA256 and timeout;
- `bindings` for Reader, tokenizer, prompt, decoder, Encoder, preprocessing,
  action menu and verifier; per-arm model checkpoints frozen during evaluation;
- independently prepared `control_annotations`, including critical evidence
  IDs, missing modality and wrong-pair donor; these never enter a model packet;
- `files`: relative-path-to-SHA256 mapping for checkpoint and modality bytes;
  `executors`: implementation-SHA-to-local-script records with path, SHA and kind;
- one `budget_caps` profile per registered experiment, using explicit wall
  seconds, active FLOPs, joules and model calls; each arm has the same deadline;
- equal declared total `split_parameter_counts` for unsplit, learned split and
  fixed split. Counts still require independent checkpoint measurement.

A source or template root cannot be given several family names to inflate the
number of independent confirmation families. Metadata validation does not prove
true novelty, semantic independence, consent or absence from model pretraining.
The external curator must review and bind the actual exposure audit.

The preregistration review is a separately pinned
`hepta.five-causal.review.v1`, scope `preregistration`. It binds the full bundle,
owner and experimenter, validity interval, revocation, exposure-audit digest,
reviewed source/family grouping and unused-in-development disposition. It states
checkpoint freeze before cohort release. Obtain its exact canonical SHA from
the independently authorized owner; a hash supplied by the experiment author
is not evidence of independence. This tool does not create external approvals.

## Controls are actual interventions

Reader arms must use the same implementation/checkpoint; no-evidence is actually
empty; premise removal exactly deletes the named critical group from the
sufficient evidence without rewriting the remaining sources. Sharing, Group and
NDU arms receive identical task inputs, questions and options.

Multimodal controls verify actual text-only extraction, registered donor-media
substitution within the same evaluation partition, modality removal and a
nontrivial temporal-position permutation. Static text/images cannot be moved
under the name of a time ablation. Split controls use identical public inputs
and equal declared parameter capacity. A temporal-shuffle contrast requires an
actual temporal media cohort; image-only tasks are not falsely treated as
having a successful temporal ablation. A separately registered image-only
stratum remains needed for an image-only claim.

These checks validate the manipulation contract, not that a temporal model
actually consumes the position field, that a Group controller learned anything,
or that a registered NDU implementation is a general FBSDE solver. Those are
native-backend and independent outcome questions.

## Blind executor ABI and failure ledger

A reviewed local executor script reads one JSON object on stdin:
`request`, `checkpoint_sha256`, `bindings`, `timeout_seconds`.
The request permits only `question`, `options`, and evidence records with
`id`, `modality`, `text`, `asset_sha256`, `position`. No gold labels, family IDs,
arm names, sufficiency annotations or critical-premise flags are sent.

The script returns exactly `request_sha256`, unmodified `answer`, and
`resources` with `active_flops`, `energy_joules`, `peak_memory_bytes`,
`model_calls`. Unmeasured counters are null, not invented zeros. Real backends
must resolve the frozen checkpoint/media map and reject unavailable resources;
the `kind=real_model` string does not establish provenance or neural execution.
The external review must verify the implementation, full runtime dependencies,
model/code inventory and physical measurement origin.

A hash-chained fsynced start event precedes each process invocation, followed by
a fsynced result. POSIX timeout kills the process group. A crash after start is
`unknown_interrupted`; it is not silently retried. Raw stdout/stderr and a
complete frozen plan are retained; output directories cannot be overwritten.
Labels are loaded only by a separate adjudication/readout invocation.

This is process-level **data minimization**, not a hostile-code sandbox. The
native host must mount only permitted public material, restrict filesystem and
network access, reset scoped state and enforce device budgets. The network
environment flag is advisory, not an egress firewall. Per-trial process startup
is deliberately included in reported wall time; this is not a benchmark of a
persistent shared worker or GPU batching. Native end-to-end worker integration
and full model/code inventory attestation remain required.

## Sequential admission and readout

E1 executes without a prior Reader qualification. Subsequent stages require a
separately pinned `reader_admission` review binding this exact bundle, original
Reader raw-output hash, judgments and actual versioned gate/trust bytes. The
existing dual-signature gate evaluator runs; a `qualified=true`-style assertion alone does not
open later stages. Cohort and model/menu identity must match the admitted stage.

The post-run `outcome_adjudication` review binds exact raw journal, bundle and
judgment digests. Judgment records contain independent bounded task score,
grounded-and-cited, exact-refusal and unsupported-claim observations. Missing,
failed, interrupted and unattempted rows stay in the planned denominator and
receive conservative zero in the failure-inclusive score. Missing adjudication
prevents a complete result; it is not silently called an incorrect answer.

Report equal-family/equal-task paired deltas, a separate old-task retention
result, worst-family delta, and approximate family-bootstrap intervals with
Bonferroni coverage across all 15 prespecified contrasts. The fixed minimum of
8 families is an eligibility floor, not a power calculation or guarantee of
valid generalization. Grouping/exchangeability and adequate sample sizes must be
reviewed. All failures remain visible. Inferential intervals are not returned
for a single template with many variants.

Resources are reported separately from quality. Unknown sensors remain null;
over-budget observations remain observable. Per-arm caps are not proof of
identical actual compute. Training, evaluation, migration, persistent-worker
amortization, physical shared-work deduplication and net split lifecycle cost
are **not** closed by this transport: `compute_matched=false` and
`lifecycle_costs_evaluated=false` remain explicit. No resource or production
superiority is issued automatically.

## Commands

```sh
python scripts/memory_cell/five_causal_experiments.py plan --output /new/plan.json
HEPTA_FIVE_EXPERIMENT_REVIEW_SHA256=<independent-preregistration-pin> \
  python scripts/memory_cell/five_causal_experiments.py preflight \
  --bundle /approved/bundle.json --review /approved/preregistration.json \
  --root /approved/read-only-materials --experiment reader --output /new/preflight.json
HEPTA_FIVE_EXPERIMENT_REVIEW_SHA256=<independent-preregistration-pin> \
  python scripts/memory_cell/five_causal_experiments.py run \
  --bundle /approved/bundle.json --review /approved/preregistration.json \
  --root /approved/read-only-materials --experiment reader --output /new/reader-run
HEPTA_FIVE_EXPERIMENT_REVIEW_SHA256=<independent-adjudication-pin> \
  python scripts/memory_cell/five_causal_experiments.py analyze \
  --bundle /approved/bundle.json --review /approved/adjudication.json \
  --journal /new/reader-run/raw-journal.jsonl --judgments /approved/judgments.json \
  --output /new/reader-analysis.json
```

Later `run` stages additionally use `--reader-review` and the external
`HEPTA_FIVE_READER_REVIEW_SHA256`, plus the independent
`HEPTA_REVIEWER_ROSTER_SHA256`; include the public `reviewer_roster` in the
reviewed Reader admission record. A missing bundle/review/model produces an
explicit blocker and exit code 2, never a green real experiment. The focused CI
runs tests and exports the plan only; it does not fabricate native evidence.
