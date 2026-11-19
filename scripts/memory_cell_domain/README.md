# Real CI memory development experiment

This directory turns pinned failure logs, repair commits and completed hosted
workflow runs into an executable, bounded memory experiment. It measures whether
a small source-trained decoder recalls a **short annotated repair ID** for an
original failure symptom. It does not execute the repair, learn a complete debug
program, certify the cause of a successful run, or establish a general memory
system. Historical development cases remain development cases.

## Source contract and producer

`domain_data.py` requires a `hepta.domain.ci-manifest.v1` JSON manifest containing
timezone-aware `registered_at`, `train_until`, `validation_until`, a `runs`
path/SHA-256 reference, and two to sixty-four case entries. Each entry supplies:

- `id`, global `root_cause`, `repair_id`, `repair_text`, `previously_seen`;
- `failed_run_id`, `success_run_id`, and an original `symptom` present in the log;
- `fix`, `failure_log`, `success_log`, each an exact `{path, sha256}` reference.

The producer requires completed failure and success runs in the same repository
and workflow. The failed commit must be a direct parent of the repair commit;
the successful run must execute that repair commit. Reusing a failure or success
run as another case is rejected. Source files, including the original manifest,
are retained and hash-bound. Offline consistency checks do not independently
authenticate a GitHub export or prove that the annotated repair caused success.

```sh
python -B scripts/memory_cell_domain/domain_data.py \
  --manifest /absolute/path/ci-manifest.json \
  --output /absolute/path/new-domain-dataset
```

Whole root-cause groups are assigned by time; a group crossing a cutoff is
purged. The same cause in another project remains the same group. Unseen-project
future cases are reported separately. A historical case cannot become
prospective merely by moving a cutoff or changing a label. Prospective status
also requires observation after the registered timestamp and an explicit
`previously_seen=false` declaration, whose external truth the producer cannot
verify. The producer currently always reports `finite_development`.

## Executed comparison

Set `PYTHONPATH` to the existing memory directories and an environment with their
installed dependencies. The model directory must be a locally staged, pinned
real pretrained decoder; the runner does not download a replacement.

```sh
export PYTHONPATH="scripts/memory_cell:scripts/memory_cell_growth:scripts/memory_cell_catalog:scripts/memory_cell_hardening:scripts/memory_cell_router:scripts/memory_cell_codec:scripts/memory_cell_population:scripts/memory_cell_domain${PYTHONPATH:+:$PYTHONPATH}"
python -B scripts/memory_cell_domain/domain_trial.py \
  --dataset /absolute/path/new-domain-dataset/dataset.json \
  --dataset-sha256 PIN_FROM_PRODUCER \
  --model /absolute/path/pinned-pretrained-model \
  --output /absolute/path/new-domain-trial \
  --seed 19031 --visits 32
```

Freeze the visit count and source manifest before viewing any result. All output
directories are new; reruns do not overwrite old evidence. `protocol.json` pins
source/dependency identities before training. Selection is persisted before
final reads, and both identities and the selection pin are checked again.

| Control | Actual work |
| --- | --- |
| Parent | Rank 4, first chronological half of source cases |
| Single | Rank 4 continuation of the verified parent on all sources |
| Expanded | Function-preserving rank 8 parent expansion, then all sources |
| Gradient split | Two parent-derived rank 4 children; whole source groups assigned using measured gradient sketches |
| Random split | Two parent-derived rank 4 children; seeded random whole-group assignment with the same feasible size balance |
| Retrieval | Exact symptom lookup, SQLite FTS5 BM25, source-fitted TF-IDF, actual frozen-decoder feature nearest neighbor and label centroid |

Every candidate sees each of its sources `visits` times and each question
template equally often. Total candidate optimizer steps and input tokens are
equal; expanded and both split controls additionally have equal total adapter
parameter bytes. A three-source cohort uses a 1/2 split. Shards may share
inherited parent roots; the experiment does not pretend fission erases ancestry.
Random and gradient partitions can coincide on tiny cohorts, which is reported.

The parent is a control, not an eligible deployment candidate. **Retrieval is
eligible for selection.** Selection maximizes supported source-only selection
accuracy, then minimizes measured deployment artifact bytes. Perfect, cheaper
source retrieval is therefore allowed to win over every neural candidate.
The exact lookup control recognizes the explicitly registered operation; its
synthetic-unknown result is not a claim of general natural-language rejection.

Each learned router is fitted on that run's measured per-child raw decoder
utility. Every positive and synthetic-negative relation is crossed with the
same four source question wordings. The negative relation requests an
unrecorded checksum and is reported separately; it is not a real OOD cohort.
Router inference receives question text only. Final routes are frozen before
decoder execution, rejected routes do not call a decoder, and separately charged
full-expert reads provide diagnostic oracle and expected-uniform scores.

## Interpretation, evidence and cost

`executed-reads.json` retains actual raw text, token IDs, prompt identity,
checkpoint binding and timing for all source, dispatched and diagnostic model
reads. `final-reads.json` retains final probes and control predictions. Outputs
are never rewritten into the expected repair ID. Each read loads a verified
checkpoint into a fresh object; this is not a fresh-process independence claim.

`known_recall` measures another wording of an already stored original symptom.
Its source-admitted score additionally requires that the selected cell's ancestry
contains that exact fact's source root. Validation/future panels report raw
repair-ID predictions only; their ancestry-admission scores are null. Future
policy transfer would need support from an authorized learned policy and actual
future task execution outcomes. Requiring a novel task's own root to be present
in old training would be an invalid test of such transfer.

The first real source cohort has three historical hosted incidents and three
root-cause groups, with no validation or future cases. Question templates and
negative requests do not increase the independent sample count. With `visits=32`
it executes 416 decoder optimizer updates, three gradient forward/backward
probes, and two separately reported 400-update linear router fits. It is a
finite development path, **not a capacity-stress or prospective confirmation
experiment**. No existing heldout cohort is used for tuning.

Costs retain actual training visits/tokens, parameter/gradient/optimizer bytes,
checkpoint files, parent/expansion ancestry, routers, source evidence, retrieval
indexes, frozen-encoder forwards, all model reads, CPU/wall time and available
process peak RSS. Full-record JSON, zlib, LZMA and SQLite are persisted and
round-tripped. Candidate training exposure equality is not equal total system
cost: gradient collection, routers, different base execution and diagnostic
reads have additional cost. Runtime/OS storage, activation attribution,
import/cold-start time and energy are explicitly excluded. Net compression,
capacity advantage, future policy transfer and production acceptance remain
unestablished.

## Review and tests

The dependency stages are: source producer plus its tests; retrieval/training
controls plus their tests; executable comparison; this experiment guide. Keep
these as separately reviewable changes. None changes an older cohort or protocol.

```sh
python -B -m unittest discover -s scripts/memory_cell_domain -p 'test_*.py' -v
```

The unit test source exports are explicitly synthetic contract fixtures. They
are never added to the real cohort or counted as scientific memory evidence.

## Source independence and observation clocks

New datasets conservatively form connected components from declared root causes,
repository-scoped failed/fixed commit ancestry, original failure-log hashes,
commit-evidence hashes, and exact repair patch content. A shared repair or source
cannot become independent by relabeling a cause. Components spanning a cutoff
are purged together; generic success-log text is not a grouping identity.
`independent_groups` counts these components, not annotation strings.

A run's `created_at`, not its last `updated_at`, establishes the earliest observed
incident time available here. Original run attempts and update times are retained.
Missing creation or attempt metadata stays explicitly unverified and cannot
qualify as prospective. A later rerun of an old task cannot manufacture a future
cohort. These checks do not independently attest an annotator's previous exposure
or detect every semantic near-duplicate; independent future acceptance still
requires the frozen source protocol and an external observation boundary.

The same recomputed component IDs feed trial admission and both learned/random
fission partitions. A single ancestry component is rejected before model loading
or output creation, even if its rows carry different root-cause labels. Exact
commit or tiny-patch matching may conservatively overmerge sequential incidents;
this reduces available sample count rather than splitting known dependencies.
Near-duplicate semantic patch detection is not implemented by exact hashing.

New output uses dataset schema v2. The loader rejects v1 inputs rather than
trusting old partitions and recomputes the full-census temporal components and
prospective flags against retained original run metadata before selecting any
training rows. Rebuild new experiments from original manifests; do not rewrite
previously frozen evidence to make it conform.
