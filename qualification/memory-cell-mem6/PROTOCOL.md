# MEM6: attribute working-state retention and qualify persistent source memory

This protocol is a pre-execution research contract. `ACCEPTANCE.json` contains
requirements, not measured results. Each run must bind both files, its complete
source closure, model, data, evaluator, configuration and original output paths
before execution. Scientific status remains **HOLD**, adoption **NoUpdate**.

## Evidence being continued

[MEM5's original report][mem5] describes 108 actor episodes, 54 paired cases and
14 source groups. With bounded memory fixed, public rule succeeded on 20/54
cases and frozen neural on 11/54: nine wins, 45 ties, no losses. Each arm includes
ten initially correct no-op successes. Eight additional successes involved
candidate-mediated text delivery; one involved image completion without text
writing. These are selector results. The earlier retention intervention was
11/54 versus 11/54. Neither 54 cases nor 108 actors are independent source
replicates, and shadow selections are not counterfactual final deliveries.

[The current blocker ledger][blockers] preserves the distinction between
reconstructing 4,000 archived files and restoring a complete owner, authoritative
state and external effects. No MEM6 result may silently close those older gates.

## Three different state layers

| Layer | Owned state and lifetime | Qualification required |
| --- | --- | --- |
| Working state | Current task observations, candidate pool and transient reasoning; reset when task/session or source scope changes | Actual paired task deliveries with only retention changed |
| Episodic/source memory | Bounded evidence records across sessions, with namespace, source/version, provenance, dependencies and current revocation frontier | Fresh reader processes, verified delivery of retained records, updates/deletions, wrong-source and rollback controls |
| Slow semantic/skill consolidation | A separately versioned candidate derived from authorized experiences | Frozen training/exposure records, independent held-out comparison, adoption/rollback and downstream use; no automatic weight change |

The existing `CandidateRuntime` is the first layer. Its `current_only` arm still
receives current OCR/public candidates; it disables earlier-observation retention,
not every form of model state. It does not resume a candidate checkpoint or carry
the pool into another operation. The new episodic store is a separate research
surface. Its deterministic process tests cannot establish learned association,
ordinary-agent integration, later-task benefit or complete owner cold recovery.

## Experiment W: frozen-public working-state retention

Entrypoint: `python -m ndu_real_runtime.run_candidate_retention_public --request
REQUEST.json --output NEW_RUN_DIRECTORY --independent-report`, with the pinned
repository and `scripts` on `PYTHONPATH`. Never reuse an existing output directory.

Both arms use public selector profile
`c9b56f198abd1737a9883326fd0c66f411e46218b126aec1e4b6f4f48e66870e`.
Only candidate retention differs: `current_only` versus `bounded`. Both retain
the same admission caps of 128 entries / 524,288 serialized bytes, original
126-feature encoding, frozen weights, encoder, OCR, controller, fixed schedule,
action space, 60-second objective and scorer. There is no fitting or rule tuning.
The unchanged model is still executed and charged, including in the public arm.

Use only released development and retention-validation sources. Bind exact
`groups_per_role`, salt `mem6-fixed-public-retention-20261110-v1` and
`sampling_profile_sha256` before reference access. Metadata-only capacity checks
may precede this freeze; a request hash alone is not proof of prior registration.
Retain a timestamped launch receipt binding the request and source commit.
Insufficient eligible sources fail admission; do not shrink the cohort after
observing outcomes or relabel sealed roles. Selection and pair order are
hash-determined. At most two workers run, with no outcome-dependent retries.

The source exclusion union includes training, tuning, quarantines, every known
prior episode plan and inherited exclusions. These two original byte identities
are mandatory:

- Retention PLAN: `488639ca2bd2b25d5c90c77b3adaf58bd8133932bb2cb1bf70fc547447d187d5`.
- MEM5 PLAN: `e33050d4b01484f8b820730117ed57659476e9e1e922ffdd43673dee7a081f9d`.

Disjointness is relative to the pinned exposure records. Complete global
exposure, provider independence and authenticated source ownership require
additional evidence. The planner/host can read released references after roster
selection for identity and routing; actors receive only the public projection.
Independent scoring starts after every actor lifetime has ended.

## Experiment E: cross-session mechanism, then real successor tasks

Start with deterministic mechanism qualification. The writer process exits;
a different process opens the persistent store and answers a new-session query.
Record process/session identity, store generation, snapshot and record digests,
source scope, retrieval result, actual delivered items and bytes. Pass no prior
conversation or working-state object to that reader. Reopening a file is a
mechanism observation, not an independent host or trust domain.

Then freeze a separate real-task protocol before using this path through an
ordinary actor/tool entry. Use ordered predecessor/successor sequences from new
authorized sources, with identical prompts, tools, model, seeds, initial effects,
budgets and graders across arms. Memory-off receives the same predecessor
experience and subsequent task, but no retained content. An unrelated cold-start
task is not the matched off baseline. The follow-up must require information or
a procedure learned earlier rather than repeat a solved prompt with its answer.

| Intervention | Held fixed | Required observable mechanism |
| --- | --- | --- |
| Memory on/off | Current task inputs, model, tooling and budget | Eligible retained content reaches only the on reader |
| Retrieval on/off | Persisted bytes and current frontier | Off returns no retrieved content while store identity is unchanged |
| Association on/off | Exact retrieved support and delivery path | A separately pinned actual head changes ranking; absent head is `unavailable`, never a successful neural ablation |
| Delivery on/off | Retrieval work and returned support | Off withholds content from the actor; receipt cannot claim it was consumed |
| Old snapshot/current frontier | Current update/revocation authority | Revoked/superseded facts and invalid dependents remain unavailable |
| Source/namespace replacement | Query wording and distractor budget | Similar wording cannot import another source's procedure or authority |

Keep exact KV, BM25/RAG, ordinary ICL and uniform experience sampling as baselines.
Provide the same authorized history and frozen byte/token budgets; charge
indexing, rendering, retrieval and context consumption. Exact KV receives only
keys available to the actor, not evaluator answer identifiers. In the store
prototype, `uniform_replay` means uniform record sampling at read time; it is not
a training-replay result. Existing uniform optimizer replay remains the retained
baseline until a separately matched training experiment justifies a change.

The prospective task roster must cover factual updates, explicit withdrawal,
dependency propagation, cross-document association, and similar requests that
need different source-specific workflows. Include fresh-session correction,
revocation followed by old-snapshot read, unrelated distractors, wrong-source
lookalikes and unanswerable cases requiring abstention. Applicable expiry and
skill-consolidation controls need explicit implementation and their own evidence;
an unimplemented surface is not a passing test.

## Outcomes, missingness and conservative acceptance

Keep every planned case and attempt. Report full-rubric terminal success,
failures/timeouts, unknown/rejected evidence, initially correct no-ops and
image-only bypasses separately. At the last WRITE_TEXT (otherwise final decision)
report candidate availability, selection and delivery with full denominators.
Unprocessed STOP has unknown candidate evidence; never borrow earlier support.
Unknown is not zero and missing-label bounds are not confidence intervals.
An independently observed terminal outcome can remain recorded when a sidecar
is missing. The primary intervention contrast requires the complete memory and
fixed-selector chains; without them its attributable outcome remains UNKNOWN.
Keep observed delivery and verified intervention outcomes in separate fields.

The case-weighted paired success difference is descriptive. For inference, first
average paired differences within each source group, then weight sources equally.
Preserve the frozen allocation of roles when resampling. The proposed benefit
gate requires at least 20 independently justified source groups, at least four
per role, source-mean gain of at least 0.05, and a positive one-sided 95% lower
bound from 20,000 stratified source bootstrap resamples (seed 20261110; empirical
5th percentile, nearest-rank definition). These are prespecified engineering
thresholds, not a power calculation or guarantees. Treat unknown memory-on
outcomes as failure and unknown off outcomes as success for this gate; also
publish the original unknown counts and both descriptive bounds.

A smaller frozen development run remains useful but cannot pass that gate.
Bootstrap inference additionally needs justified source independence; grouping
labels or source hashes alone do not provide it. The report computes this
interval with `candidate_retention_inference.py`; its numeric-threshold flag
does not authenticate source independence or grant adoption. Bind that analysis
implementation before reading outcomes and retain its original profile.
Separate gains on initially incorrect tasks from preservation of correct state.
The main working-state contrast is the single primary comparison. For future
cross-session claims against four baselines, freeze four contrasts and use
one-sided 98.75% lower bounds (Bonferroni family alpha 0.05); exploratory
head/delivery controls do not create extra independent samples.

Any wrong-source disclosure or resurfacing of a revoked/deleted dependency fails
the corresponding mechanism/adoption gate even when aggregate success improves.
Zero observed failures is finite-suite evidence, not proof of absolute safety.
Report actual whole-campaign and per-layer CPU, wall, OCR/model calls, indexing,
retrieval, delivered bytes/tokens, storage, failures and recovery. Do not sum
overlapping envelopes. Unknown energy/provider charges stay null; full-cost
qualification remains open until measured. A benefit on a cost-blind score does
not establish a resource-adjusted advantage.

## Recovery and adoption boundary

Snapshot-only rollback is tested against the current authoritative frontier.
Rolling back or tampering with both the authority database and snapshot is a
different threat; same-owner SQLite files do not protect against it. Namespace
labels, digests and process restarts are not authentication or external custody.
Current deletion tests cover eligible retrieval/delivery, not forensic erasure
from archives, logs, backups or previously adopted weights. Full-owner recovery
must additionally bind current authority, credentials, permissions, effects,
idempotency/fencing and next-task behavior across independent restart/custody.

Passing W qualifies only its working-state contrast. Passing deterministic E
qualifies only the tested store mechanism. Neither authorizes production
adoption, a learned semantic/skill update, general memory superiority or RSI.
Those decisions require independent real successor-task benefit, all applicable
deletion/source controls, observed complete cost, exact-source required CI and
full-owner/effect recovery. Every unresolved gate remains explicit.

## Research basis

[Continual Learning Bench][cl] (2026-06-04) compares experience-based gain with
underlying model capability and finds strong ICL in its tested configurations.
This motivates retaining ordinary ICL here; its numbers are not Hepta results.
[PAST-Bench][past] (2026-08-04), with [released implementation][pastcode], uses
matched fresh-session persistence controls and inspects save/retrieve/update
paths. Its synthetic tasks and mechanism-consistency metrics do not establish
causal necessity or broad RSI. This protocol therefore additionally requires
content removal/replacement, source switches and actual successor deliveries.

[mem5]: https://github.com/TrillionniumFoundation/hepta-private-ci/blob/e073420866be71bb6879d658763fc2cba36a94d3/qualification/memory-cell-mem5-selection/run-001/RESULTS.md
[blockers]: https://github.com/TrillionniumFoundation/hepta-private-ci/blob/e073420866be71bb6879d658763fc2cba36a94d3/qualification/memory-cell-mem5-selection/run-001/BLOCKERS.json
[cl]: https://arxiv.org/abs/2606.05661v1
[past]: https://arxiv.org/abs/2608.04003v1
[pastcode]: https://github.com/Gen-Verse/PAST-Bench
