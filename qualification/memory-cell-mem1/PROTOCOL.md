# MEM-1: memory and association Cell qualification protocol

Protocol date: 2026-11-08. Scientific qualification: **HOLD**. Production adoption: **HOLD**.
This file specifies required behavior and evidence; it is not an execution receipt.
The result register below stays unqualified until exact run artifacts support its entries.

## 1. Scope and claims

The first campaign is a fixed-capacity reference with native Rust fast-memory operations
and Python orchestration over a synthetic continuous A -> B -> A stream.
Plan: seven arms, five independent synthetic seeds, 35 arm/seed runs per condition,
including failures. Before the first campaign, add a paired stationary-owner condition:
70 planned runs total. `--stationary` retains fast state at B; the main condition exercises
the rule replacement, source revocation and scope change with reset/rebuild.
These seeds are not five independently pretrained language models.
The reference is inspired by test-time memory and consolidation research; it is **not a
Titans, Hope, or Sleep reproduction**, and it does not establish biological equivalence.
Synthetic results can qualify the exercised mechanisms and identify failures.
They cannot establish an advantage on real agent tasks, autonomous RSI, or live deployment.
No live agent integration, current production-owner connection, or adopted model is implied.

## 2. Four layers and ownership

| Layer | Authoritative owner and content | Update and recovery contract |
| --- | --- | --- |
| Working state | Episode executor: hidden state, cache, candidate trajectories | Bounded fast updates; explicit episode start/end/reset; never a fact or permission owner. |
| Episodic facts | Fact/source owner: records, provenance, revisions, time, scope | Owner controls correction, supersession and revocation; resolve current eligibility at use. |
| Private fast memory | One Cell/scope: learned associations and adaptation state | Independent state identity; bounded mutable weights and update state; checkpoint/reset/migrate explicitly. |
| Slow knowledge | Candidate artifact, then selected model/adapter owner | Evaluate against retention, plasticity, truth and cost gates; explicit adopt or `NoUpdate`. |

Online updates to private memory must not mutate the selected shared base/adapter.
Fast memory proposes associations or references; it does not make remembered claims true.
An old fact can remain in a historical journal without being eligible for current use.

### 2.1 Identity and state API requirements

Bind Cell ID, owner/scope, base and adapter digests, encoder identity, state schema,
learning-rule identity, numeric profile, update-state schema and memory generation.
Bind checkpoints to those identities, their parent checkpoint and exact state bytes.
Include weights, optimizer/momentum where used, RNG state where used, update count,
replay references and the resource ledger needed to resume without free extra work.
Operations have explicit initialize, observe/update, propose, checkpoint, restore,
reset and migrate semantics; these are protocol roles, not promises of live RPC methods.
Reject mismatched identity, corrupt state and stale generation before state replacement.
Migration requires a named transform and receipt; a reset is reported as a reset.
Restoring a checkpoint cannot restore authority that the current owner has revoked.

### 2.2 Owner callbacks required before production use

Use the existing owner-bound retrieval contracts in `codex-rs/hepta-memory-retrieval`;
generator receipts and recall packets are evidence, not grants of authority.
The production integration must exercise the following callbacks against actual owners:

| Boundary | Required current-owner decision and receipt |
| --- | --- |
| `Recall` | Resolve proposed record/source IDs, exact revision, current scope, validity, supersession and permission before returning evidence or emitting a factual answer. |
| `Replay` | Separately authorize use for learning; permission to recall does not imply permission to train or retain a replay sample. |
| Training admission | Recheck replay eligibility immediately before training; bind the consumed source set and owner epoch to the candidate. |
| Candidate adoption | Recheck training-source revocation, evaluator identity, compatible state and selected parent generation; commit under a generation fence or return `NoUpdate`. |
| Recovery/use | Resolve current owner state again after restore; reject old grants, stale facts and cross-scope references. |

Scope and eligibility apply before scoring or candidate construction can expose data.
Revalidate at final use, or use an owner-issued epoch/fence that makes the decision atomic.
Exercise revocation after selection/before training and after training/before adoption.
Synthetic callbacks only qualify the reference owner; they do not certify a live owner.
Keep lineage through generated replay and distilled candidates; generated text is not a
new independent authority for facts copied from a revoked parent source.
Filtering returned references is not parameter unlearning: contaminated fast/slow state
must be invalidated, reset, isolated or rebuilt from eligible data with a recorded policy.

## 3. Continuous stream and probe panels

Freeze the stream generator, seed list, initial state, features, task split and budgets
before examining campaign results. Run every arm on the same seed-specific observations.
The actor receives only observations available at that point; the evaluator keeps targets.
Use predict-then-observe/update ordering. Evaluation probes do not update state or replay.
Probe labels, confirmation results and future owner events never enter training.

| Panel | What changes and what counts as correct |
| --- | --- |
| A-stable | Unchanged A rules remain valid after B; score retention only on this panel. |
| A-superseded | An overlapping rule gets a new authoritative revision; the old answer is stale, not successful retention. |
| A-revoked | Source or scope eligibility is withdrawn; abstain unless another current eligible source supports the answer. |
| A-composition | Familiar constituents appear in withheld combinations; hold out complete combinations, not just duplicated query strings. |
| A-recovery | Pair uninterrupted execution with checkpoint/restart/restore; also exercise incompatible migration and explicit reset. |

Measure after learning A, during B, immediately after B, and on the return to A.
Keep unchanged-rule retention separate from correction, revocation and relearning.
The final A evaluator follows current owner truth; it does not blindly reuse old labels.
Declare how many new observations are allowed on return before measuring reacquisition.
Keep source/episode groups disjoint between tuning and confirmation data.
Synthetic owner events and hidden test keys must not be recoverable from arm names.

## 4. Seven-arm reference matrix

These are logical arm IDs; the execution manifest must map each to its exact configuration.
An unimplemented component stays missing and cannot be replaced by a renamed baseline.

| ID | Arm | Main comparison |
| --- | --- | --- |
| M0 | Budgeted RAG | Retrieval-only reference with the same current-owner checks. |
| M1 | RAG plus ordinary replay | Control for replay exposure and additional adaptation opportunity. |
| M2 | Ordinary recurrent state | Control for persistent state without fast-weight learning. |
| M3 | Fast memory, no sleep | Isolate online fast adaptation. |
| M4 | Fast memory plus uniform consolidation | Control for consolidation computation and uniform sample selection. |
| M5 | Fast memory plus structured consolidation | Test selection across recent, surprising, rare-goal and retention samples. |
| M6 | M5 plus stabilization | Isolate the registered stabilization rule with other settings fixed. |

Specify what M1 actually updates; replaying a query without learning is not a matched
extra-training control. Register the M6 objective/anchor and coefficient before results.
Compute surprise before receiving the observation's target or supervised feedback.
Compute rarity from past eligible experience, not from future or confirmation statistics.
Selection, mixture weights and capacity are fixed in the confirmatory configuration.
Further recent-only, surprise-only and retention-only runs are separately labeled ablations.

## 5. Capacity, training and compute fairness

Use common evidence access, encoder, eligible observations, query opportunity and scope.
Register a common resource ceiling and each arm's useful allocation; record actual use.
Count mutable weights, recurrent state, replay buffer, optimizer state and candidates.
Record both logical capacity and bytes; equal slot counts do not establish equal memory.
The fixed-capacity campaign must not add experts, hidden replay storage or adapter capacity.
Match updates, examples/tokens, candidate capacity and tuning opportunity in comparisons
that claim a consolidation benefit; report any mismatch as a limitation, not a pass.
Additional training must be compared with M1/M4, not only with the no-sleep arm.
Do not pad an inefficient arm with idle work to claim useful-compute equality.
Report encoder, retrieval, online updates, replay selection, consolidation, evaluation,
checkpoint/restore, retries and failed attempts separately, plus full wall time.
Keep operation counts distinct from measured FLOPs, latency, energy or money.
Five seeds are a pilot: do not infer a population benefit from pooled query counts.

## 6. Outcomes and gates

Retention: report `A_stable_after_B - A_stable_after_A` with both raw accuracies.
Plasticity: report B's prequential curve, sample/compute cost to a preregistered threshold,
and reacquisition cost; a run that never reaches the threshold is censored, not zero-cost.
Truth: count unsupported, superseded, revoked and out-of-scope assertions separately.
Report answer coverage and conditional error among answered probes; all-abstain is not
successful memory. Report composition separately from familiar-item retrieval.
Recovery: compare outputs and state receipts with the uninterrupted paired run, and
record whether migration preserved state or deliberately reset it.
Costs: expose per-arm totals, peak capacity and the denominator of every attempted run.
Aggregate paired seed differences; retain seed-level rows and uncertainty where justified.

Technical qualification requires correct current-owner behavior on exercised negative
cases, intact immutable shared identities, bounded state and accounted recovery costs.
Required negative cases include stale/revoked facts, cross-scope access, restore after
revocation, identity mismatch, damaged checkpoint and rejected stale-generation writes.
Missing tests stay untested; zero observed errors is not a proof of universal correctness.
Scientific qualification requires a frozen real-task confirmation panel, independent
training repeats, matched resources and a preregistered practical benefit threshold.
Production qualification additionally requires actual owner callbacks, release identity,
real successor consumption, crash/revocation races and rollback without resurrected grants.
Failure of a gain, validity or compatibility gate yields `NoUpdate` or **HOLD**.

## 7. Result register: populate only from retained execution artifacts

Do not overwrite earlier attempts or retroactively label tuning runs as confirmation.
Every populated value must cite a path/URI, size or row count as applicable, and digest.

| Required record | Value / evidence status |
| --- | --- |
| Exact source commit/tree, uncommitted patch and binary identity | UNRECORDED |
| Protocol/config/stream/seed manifest identities | UNRECORDED |
| Seven arms x five seeds: attempted/completed/failed counts | UNRECORDED |
| Native tests and required repository validation commands | UNRECORDED |
| Per-query raw outcomes and per-seed metrics | UNRECORDED |
| Capacity, update-count and complete cost receipts | UNRECORDED |
| Recovery, revocation and owner-race receipts | UNRECORDED |
| Technical reference verdict and exact exercised scope | UNRECORDED |
| Source-anchored real-task confirmation | NOT EXECUTED BY THIS PROTOCOL; HOLD |
| Live owner integration, successor consumption and production adoption | NOT ESTABLISHED; HOLD |

The execution report may supply these records by reference; this protocol alone grants
neither scientific qualification nor production adoption.

## 8. Separate follow-up: source-anchored real tasks

Register real task/source provenance, current data eligibility and source-group splits.
Freeze train/development/confirmation and old-task retention panels before tuning.
Use an independently identified evaluator and task outcomes beyond synthetic retrieval.
Keep the strong RAG/replay/recurrent baselines, complete metering and actual owner hooks.
Estimate independent-repeat requirements from pilot variability; do not reuse five
synthetic seeds as evidence of adequate power for real-task claims.
Test selected-candidate consumption by a real successor and a valid `NoUpdate` path.

## 9. Primary research and evidence boundaries

Links identify the original works; biological findings motivate hypotheses, not API safety.

| Work and date | Verified claim and limit |
| --- | --- |
| [Titans](https://papers.neurips.cc/paper_files/paper/2025/hash/a4ca07aa108036f80cbb5b82285fd4b1-Abstract-Conference.html), NeurIPS 2025; [full text](https://arxiv.org/html/2501.00663v1) | Online associative neural memory uses learned update/forgetting mechanisms; this reference does not reproduce the paper's architecture or training. |
| [Nested Learning](https://papers.neurips.cc/paper_files/paper/2025/hash/4309616aaed8e848009bc4a7ef73b493-Abstract-Conference.html), NeurIPS 2025 | Nested optimization, context flows and memory update frequencies motivate explicit update rules and timescales; no generic no-forgetting guarantee follows. |
| [Language Models Need Sleep: Learning to Self-Modify and Consolidate Memories](https://arxiv.org/abs/2606.03979), 2026-06-02; v2 2026-07-10 | Behrouz et al.: Knowledge Seeding, capacity growth and dreaming; isolate added capacity/training from consolidation effects. Preprint. |
| [Do Language Models Need Sleep? Offline Recurrence for Improved Online Inference](https://arxiv.org/abs/2605.26099), 2026-05-25; v3 2026-06-05 | Lee et al.: offline recurrence updates fast weights; a separate preprint, not the above dreaming/distillation method. |
| [Human hippocampal ripples coordinate planning sequences and compositional representations in neocortex](https://pubmed.ncbi.nlm.nih.gov/42092183/), Nature Neuroscience, 2026-05-06 | Intracranial recordings in 28 epilepsy patients link replay, prefrontal activity and inference. Observational evidence; no ripple intervention establishes causation here. |
| [Hippocampal-cortical coupling dynamics drive system consolidation of remote memory](https://doi.org/10.1016/j.celrep.2026.117810), Cell Reports, online 2026-08-07 | Animal recordings plus closed-loop optogenetic perturbation support causal coupling effects in the studied fear-memory circuit. |
| [Selection of experience for memory by hippocampal sharp wave ripples](https://pubmed.ncbi.nlm.nih.gov/38547293/), Science, 2024-03-29 | Yang et al.: waking/sleep replay selection evidence. Do not relabel this recording study as the unspecified “2024 Science intervention study”; that citation remains unresolved. |

The 2024 citation correction does not weaken the engineering requirement to test causal
ablation effects directly. No neuroscience result substitutes for MEM-1 execution evidence.

## 10. Initial harness implementation mapping and remaining gaps

Reviewed `scripts/memory_cell_mem1/{environment,run,native,verify_results}.py` and the
`mem1_fast_memory` Rust example. A run manifest pins the actual source and binary bytes.
This mapping describes implementation scope; it does not waive Sections 2-8 requirements.

| Logical ID | Actual arm | Implemented behavior and comparison limit |
| --- | --- | --- |
| M0 | `rag` | Strong exact-key lookup: after first exposure, return the current owner label. No approximate search or language generation. |
| M1 | `rag_replay` | Combine the replay-trained native readout with a fixed +0.5 prior on the retrieved current label, then take argmax. Predictions affect answers; superiority to M0 is not presumed. |
| M2 | `recurrent` | Fixed `tanh(0.5*h + key)` features with the same adaptive native linear readout; not a learned recurrent-network baseline or a no-fast-weight control. |
| M3 | `fast` | Fixed-capacity normalized-delta associative weights; no offline rehearsal. |
| M4 | `fast_uniform` | M3 with uniform eligible replay, 64 updates after A1 and 64 after B. |
| M5 | `fast_structured` | Same rehearsal count; cycle recent, predictive uncertainty, rare stored label and A-retention selection. Uncertainty is not Titans' gradient surprise. |
| M6 | `fast_stabilized` | M5 plus 0.25 teacher/0.75 label targets after the B boundary; teacher is a frozen private-state clone, not a slow model. |

Inputs are 16-dimensional seeded random features, eight label classes and 24 named sources;
the replay pool holds at most one latest experience per source, with capacity 24.
No pretrained base model or adapter is loaded; frozen-model identifiers are fixture
commitments. `model_adoption=NoUpdate` records absence of shared-model adoption.
Sleep updates the active private fast state in place, then saves a rehearsal checkpoint.
It performs no slow-adapter distillation, independent candidate evaluation or adoption.
At B, the owner replaces A:8/A:9, revokes A:10 and moves A:11 out of scope; native state
is reset and rebuilt from eligible A rows. Every retained key is re-encoded at the current
generation; old mixed recurrent context is not replayed after revocation. This condition's
retention includes reset/rebuild. The stationary control keeps the same labels, scope and
source generation and does not reset at B, permitting a separate interference measurement.
The composition panel returns a pair of independently predicted constituent labels;
it does not test a new relation, multi-step inference or learned composition operator.
All arms use the same synthetic final-answer eligibility gate. Zero forbidden answers
would support that exercised gate, not learned truthfulness or production authorization.
The stale counter detects exact old labels for the two superseded A rules; it is not a
general provenance/citation validator, and wrong/invalid assertion counts stay separate.
Recall/Replay checks are sequential; revoke-during-training/adoption races and real owner
authentication are untested. The separate store and evaluator are in one Python process.
Recovery restarts a native worker and checks its state digest, one prediction and working
state; Python owner/RNG and any teacher worker remain alive. Full-owner crash recovery,
an uninterrupted paired trajectory and a schema-transform migration are not exercised.
Resource limits are common ceilings, not equal useful work, equal wall time or equal RSS.
Reserved native-state/pool payloads exclude process overhead; numeric multiplication
counts exclude hashing/IPC. Wall time includes both, and native child CPU is reported where
the platform exposes it. RAG skips unused numerical predictions during tasks, but all arms
share the qualification checkpoint/restart harness. Timings are not an optimized production
RAG benchmark. Sleep arms receive 128 additional updates. Owner checks are counted at the
resolver; replay pool payload uses its observed peak, with resource checks during execution.
`verify_results.py` checks recorded probe/summary consistency, update counts, candidate
bytes and reported resource limits; it shares the synthetic expected labels and is not
an independent real-task evaluator or a complete reconstruction of all compute costs.
Keep actual measurements in retained reports; scientific and production qualification
remain **HOLD** until the original missing comparisons and integration evidence exist.
