# Hepta neuroscience mechanisms — shadow qualification (2026-11-10)

**Status:** RESEARCH_ONLY / DENY_ALL. These files are a small, read-only Python
stdlib reference and evidence preflight, **not** a model-training implementation,
a live Cell owner, a StageOwner port, a production scheduler, an independently
attested evaluation, or evidence of scientific gain. They do not change selected
weights, install a learner, revive deleted records, or make any external effects.

## Native Q24 research comparator

`codex-rs/hepta-neuron/src/plasticity/temporal_credit.rs` now provides a
bounded, **read-only Q24** temporal-credit comparator alongside the existing
history-averaged `accumulate_plasticity`. Unlike the Python shadow, it uses
the canonical fixed-point arithmetic, parameter-group projections and trust
region; it binds declared source receipt, checkpoint, model, owner scope,
generation and logical action identity to each feedback record. It rejects
future action credit, evaluation-split labels, duplicates, stale identity and
feedback that precedes its action. It reports missing/late feedback separately.
It does **not** authenticate those declarations against a real source/owner
or run a native trained Head. Any apparent owner field is untrusted until
an independent verifier validates real receipts. No candidate is adopted.
The native component is exercised with
`cd codex-rs && cargo test -p codex-hepta-neuron --lib`.

**Related parallel research:** PR #5739
(https://github.com/TrillionniumFoundation/hepta-private-ci/pull/5739)
already contains an information-matched contextual policy-gradient comparator
and synthetic costed microbenchmarks. Its report finds equivalence to the
correctly routed rule on that proxy, some slower-lineage regressions, and
exact-key RAG dominance. Do not double-count its synthetic seeds as independent
confirmation, and do not rebrand a three-factor update as a new algorithm.
The present Q24 code is a numerical/identity-contract extension, **not** a
replication or refutation of PR #5739's task-level results.

Existing canonical mechanisms remain in
`codex-rs/hepta-neuron/src/{plasticity,qualification}.rs` and the
`docs/learning/NEURAL_BIOMIMICRY_SPEC.md` contract. That plasticity reference
aggregates eligibility history before modulating it. This qualification pilot
provides a **separate** time-indexed, source-bound research comparator, without
silently changing that production-adjacent API.

## Run

### Real-time and source-level research extension (2026-11-12)

`real_time.py` separates reward occurrence discounting, state response, update
opportunities and eligibility decay in microseconds; foreign clock/boot envelopes
are rejected before classifying feedback as future. `source_contrast.py` freezes
the source roster, ability/evaluator and offered budgets, compares original
information bytes, and reports equal-weight source differences. UNKNOWN/missing
outcomes withhold the planned-set summary. `learning_progress` retains interval
or right-censored attainment. All identities remain unverified declarations.
See [FOUR_TRACK_PROTOCOL.md](FOUR_TRACK_PROTOCOL.md) for the four research tracks.
Run all reference checks with `python3 -m unittest discover -s . -p 'test_*.py'`.
These APIs do not train or adopt weights; real-owner integration remains open.

```sh
cd qualification/neuroscience-20261110
python3 -m unittest -v test_study.py
python3 study.py --trials /path/to/frozen-b-evaluation.jsonl
```

No external dependencies, network, GPU, model weights, or credentials are
needed for the contract tests. No evaluative data is fabricated by the runner.
The tests use deliberately synthetic fixtures to validate mechanics only.

## Four falsifiable work packages

| Work package | Research arms / negative controls | Evidence that would be needed |
| --- | --- | --- |
| Different clocks | PERC slow, MEM immediate writes, CTRL calibration, ACT slow consolidation; **each** interval registered in logical sequence units; equal training-update budget controls | Actual newly trained head/adapter, frozen model identity, same opportunity budget, qualified next-task and retention evaluation; clock spacing itself is not a benefit |
| Local credit | Routed vector × local eligibility vs cyclic-shuffled routing **with the same complete modulator vector**; scalar projection and no eligibility are additional, not fully information-matched, references | Independently observed effects, owner-linked action and feedback receipts, permutation/blind checks, full tuning and labeling cost; improvement over shuffled routing |
| Delayed feedback | Time-aligned eligibility at action time, decay by lag and finite window, no-eligibility and temporal shuffles; short/dense vs long/sparse feedback as a preregistered moderator | No hindsight/future leakage; action time before feedback availability; benefit measured at full training, inference and feedback cost in ACT/CTRL; no unearned claim for dense labels |
| Distinct memories | Exact-key RAG, uniform replay, stratified fact/episode/skill/recovery replay, no replay and old-task retention | Tombstone/revocation & provenance enforcement; matched storage/write/read/index/retrieval costs, conflict and interference cases; improvement over exact-key RAG, not only over no-memory |

The values `PERC=16`, `MEM=1` etc. used in tests are **illustrations**
of an explicit update schedule in logical steps. They are not a biologically
deduced or empirically optimal policy. Native owner integrations must register
their own clocks and evidence against actual versioned data.

`study.py` returns immutable dataclasses and research-only receipts.
`time_aligned_credit` consumes a train-only action/eligibility transcript and
independent feedback **declared** to have become available at specific logical
steps. It prevents duplicated feedback, updates based on feedback arriving
after the training cutoff, and feedback occurring before an action. It clips
per-group and global L1 proposal deltas. Numerical representation is Python
float for reference testing, **not** the production Q24 bit-exact contract.
**Frozen-selection view vs forensic audit.** `time_aligned_credit` returns a
full-audit receipt whose `future_withheld`, `unobserved_action_count`, and
`transcript_digest` fields can depend on feedback that arrived after the
training cutoff. These are post-hoc **forensic only**, never candidate or
controller features. `frozen_credit_view(receipt)` produces a typed frozen
shadow projection containing only the arm, clipped deltas, matched/expired
counts observed by cutoff, causal training digest, and `DENY_ALL` status.
Its payload is invariant to valid future-only receipt additions and label
changes, unlike the full-audit payload. The projection is not a native
Owner-authenticated receipt, does not replace correct event-availability
checking, and is not a production admission or adoption interface.

The action's `source_digest` and outcome's `receipt_digest` are syntax-checked
SHA-256 strings: **no signer, root authority, source provenance or real effect
is verified here**. Owner authentication and true outcome attestation remain
separate blockers.

`cadence_gate` reports at most `REVIEW_CANDIDATE`, never promotion. A clock
opportunity is consumed whether it passes the evidence gate or not. Actual
Adopt/NoUpdate, checkpoint CAS, next task, version rollback and cold recovery
must occur in the original StageOwner and lifecycle with an independent reviewer.

`select_replay` is an algorithmic selector: uniform is hash-seeded, stratified
round-robins kinds, and exact is source-key matching. These methods are
**not** interchangeable: exact-key RAG is a strong baseline. The selector
excludes tombstoned, revoked or future-dated entries. An optional explicit
`logical_id` groups successive revisions of one declared memory object; only
the most recent visible non-revoked revision can be replayed, and a visible
tombstone or rights revocation blocks the whole group (even against an unsigned
later revision). A matching query `key` alone does not imply common ownership
or deletion: distinct objects can share a key. Logical IDs and timestamps are
self-declared, not attested; actual deletion owner must still enforce authenticated
CAS/purge/irreversibility, valid re-grant policies, and budget independently of
this demo.

## Frozen full-cost evaluation input

`paired_evidence` expects one `TrialRow` per
`(episode_id, seed, family, arm)`; **all four arms** must appear. The JSONL
fields exactly match the `TrialRow` dataclass in `study.py`.
For each paired block it requires identical:

- `workload_digest`: prospectively sampled task/evaluation instance;
- `ability_digest`: actual capability, base model and eligible trainable
  parameter budget (baseline model capacity must not be weaker);
- `evaluator_digest`: held-out and frozen evaluator;
- `feedback_budget_bits`, `query_budget`, `training_budget`,
  `compute_budget_us`: opportunity ceilings (not claimed realized costs).

`gross_value` and `full_cost` are in the **same declared utility unit**.
Full cost must include compute, optimizer and retry, data/labeling, delays,
inference, storage, retrieval, verifier and failed actions, supervision and
risk losses where relevant. Report both net utility and actual full cost.
`retention_value` is measured separately on a frozen old-task panel. Missing
old-task measurements remain null; never impute 0 or success.

The preflight's matched primary comparison is routed minus shuffled, both
using the **same supplied vector and budget**. Scalar uses an intentionally
coarser projection of that same vector; do not interpret routed-minus-scalar
as an equal-information attribution result. Exact one-sided sign-flip p-values
are **exploratory and unadjusted**, use seed-clustered paired units, and are
reported only up to 16 seed units. Seed exchangeability, evaluator
independence, complete cost accounting, missingness, and multiple-testing
corrections are NOT established by the JSONL flags. The output always says
`HOLD_NO_PRODUCTION_AUTHORITY`.

### Required registration before any effectiveness claim

1. Freeze source tree, base/adapter/tokenizer/model/dataset/codec fingerprints,
   deployment baseline, task generator and evaluator, including units and
   independent future episode seed assignment. Do not reuse selection seeds.
2. Run the ordinary core × controller factorial
   `A=Ordinary`, `B=NDU`, `C=Hepta`, `D=Hepta+NDU` where applicable.
   Report B−A, D−C, D−B and the interaction, not only D−A.
3. Pre-register delayed **sparse and dense** reward, text sufficient,
   multimodal complement, selective correction, prepare-then-benefit,
   timely stop, and an independent retention panel. Include exact-key RAG,
   matched ordinary gradient/VOI/MPC, random router and a cost-matched
   fixed-clock baseline. Separately test whether the true causal route,
   rather than extra information, yields benefit.
4. Record raw time-indexed owner receipts, eligible observations/actions,
   decision-memory changes, all failures/cancellations and complete
   resources. Separately prove a later full product sequence:
   task A → real training → *independent* evaluation B → selection/NoUpdate
   → distinct task C → different worker and cold recovery.
5. Compare independently trained seeds, seed-cluster confidence intervals and
   declared family-wise corrected tests. Pre-register a **practical net-effect
   threshold** and noninferiority tolerances for old-task retention and safety.
   Nulls, missing labels and low-powered negative results remain HOLD.
6. Only native owner evaluation may attest source/label provenance and actual
   external effect. A passing unit test or JSON report alone is never
   scientific, product, security or deployment qualification.

## Mechanism inspiration (not equivalence)

The 2025 Nested Learning update-frequency viewpoint and the cited 2026
cell-type plasticity, dendritic guidance and diffuse neuromodulation research
motivate ablations—not a proof of biological identity, universal
backpropagation, solved continual learning, or an optimal number of Hepta
lineages. The references and dates below are discussion inputs, not
independently reverified source evidence by this qualification:

- https://proceedings.neurips.cc/paper_files/paper/2025/hash/4309616aaed8e848009bc4a7ef73b493-Abstract-Conference.html
- https://pmc.ncbi.nlm.nih.gov/articles/PMC13473605/
- https://www.nature.com/articles/s41586-026-10190-7
- https://pmc.ncbi.nlm.nih.gov/articles/PMC13598169/
- https://arxiv.org/abs/2610.25858

### Frozen shadow-credit input boundary

`frozen_credit_view(time_aligned_credit(...))` only redacts **output** fields.
A future malformed/orphan feedback receipt can still make full forensic
validation fail before projection. For shadow candidate evaluation use
`frozen_credit_from_prefix(...)` instead: it filters records with
`available_sequence > cutoff_sequence` **before** validation. In-prefix
invalid observations remain hard failures. All timestamps are still
self-declared here, and neither API is an owner-attested source or a
production selector.

## Promotion blockers (all OPEN by default)

- Native owner-bounded, version/receipt-attested time-aligned training (no fake
  provenance, future labels, version drift, overwrite or independent-eval leakage).
- Fixed, compatible model capacity, matched tuning budgets and complete cost
  observations across routing, clock, feedback-density and memory arms.
- Prospectively acquired **real** sparse/dense feedback with counterbalanced
  independent seeds, the full task-family matrix and old-task retention.
- Independent evaluator, statistical multiple-comparison registration, positive
  effect above the practical threshold, plus correct `NoUpdate` negatives.
- Production lifecycle: model candidate → owner-attested select → next task
  → cold recovery and rollback, with zero unexpected authority or duplicate effect.

Failing or unresolved gates remain HOLD; do not auto-promote this code.
