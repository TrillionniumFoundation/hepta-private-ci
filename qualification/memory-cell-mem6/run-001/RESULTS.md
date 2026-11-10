# MEM6: attributed working-state retention and fresh-process memory qualification

## Decision

**Scientific acceptance: HOLD. Production adoption: false. Action: NoUpdate.**

This run completed 276 real actor episodes over 138 paired cases from 34 newly
allocated source groups, plus a separate 18-scenario deterministic memory
mechanism suite. All planned actor episodes completed and all terminal outcomes
were observed. Complete evidence and intervention checks qualified every actor
episode in the reported primary comparisons.

The fixed public selector reproduced a positive terminal-outcome difference on
new sources. Working-state retention produced two additional successes, but
failed the prespecified source-bootstrap lower-bound requirement. The
fresh-process mechanism suite passed; it did not evaluate actual agent behavior
on unseen successor tasks.

| Experiment | Treatment | Comparator | Paired results | Initial no-op successes |
| --- | --- | --- | --- | --- |
| Fixed-public working-state retention | bounded 30/84 | current_only 28/84 | 2 wins, 82 ties, 0 losses | 16 per arm |
| New-source selector replication | public_rule 21/54 | frozen_neural 13/54 | 9 wins, 44 ties, 1 loss | 10 per arm |
| Same-authority fresh-process mechanism suite | 18/18 scenarios pass | deterministic interventions | 18 new consumer processes; 3 exited writers | Not an actor-task success rate |

The two actor experiments use disjoint source groups. Their outcomes must not
be pooled as one memory-effect estimate. Earlier MEM5 results are historical
context and are not added to this run as independent confirmatory evidence.

## Frozen source, allocation and execution

- Execution source: `8cf848babdd897e9f38642d5faf3ba0f72a1303c`.
- Source capsule: 110 files, 410,861 bytes;
  SHA-256 `45b737c45ad1d29de5b58bced568fa7f8469963c8845fd18bac3fedf95064b81`.
- Exact source bytes, model weights/parameters, OCR inventory, evaluator,
  control schedule, episode budgets and prior-source exclusions were pinned.
- Both cohorts were frozen before either new campaign observed an actor outcome.
  Retention sources were prospectively reserved from selector allocation.
- Retention: 20 sources, with 16 development and 4 retention-validation sources;
  84 cases and 168 actor episodes.
- Selector: 14 other sources, with 10 development and 4 retention-validation
  sources; 54 cases and 108 actor episodes.
- Retention plan SHA-256:
  `a8618ffa21985c8e9267d8fd50663bd9737568a14d05904ce05d5c6efea92e53`.
- Selector plan SHA-256:
  `0ddd9e67a302e57bb2b565f978230b1413bcd1c56f6cc21365f106552b592194`.
- Both actual run plans matched their pre-execution frozen plan bytes.
- Execution completed on ai395 on 2026-11-10 at 13:20:11 UTC. Both actor
  campaigns and the mechanism suite returned exit code 0.

The role named `retention_validation` is a released development-validation
role. It is not a sealed confirmation set. Source independence and the complete
historical exposure roster have not been independently authenticated.

## 1. Working-state retention: a localized gain, below the adoption gate

The experiment fixes the MEM5 public selector and changes only the offered
candidate-pool retention mode. `current_only` still receives the current
observation; it is not an agent with all internal memory removed. Both arms use
the same 128-entry / 524,288-byte admission caps and 60-second episode budget.
The store in this experiment is reset for each actor episode.

The primary all-planned result is 30/84 versus 28/84: a pair-weighted difference
of 2.38 percentage points. Neither arm has a missing terminal outcome, failed
attempt, timeout, or rejected primary episode. Each arm includes 16 initially
correct no-op successes. Among the 68 initially incorrect cases, the result is
14/68 versus 12/68. There are no bypass successes in this comparison.

The two winning pairs are:

| Pair suffix | Case | Source | Report-level mechanism |
| --- | --- | --- | --- |
| `bd1daa4059274fa7d85d` | `case-25169c3b7a4bb89231cd56aa` | `merchant-bcea7cef234c903b8657e3b2` | Earlier correct candidate remains available with bounded retention; absent from current-only decision roster |
| `686fc2e67e7000826e40` | `case-b96281f1dd3b51dc9bb69ab7` | `merchant-58a28471023079b3c7ced730` | Same availability-to-selection-to-delivery pattern |

Both cases start incorrect, both arms previously observe the relevant text,
and the decisive report anchor is step 2. Bounded retention makes the correct
candidate available, selects it and successfully delivers it. Current-only
retention loses that candidate from the offered roster. These are neither
initial-state credit nor bypass successes.

A separate raw audit completed pair `686fc2e67e7000826e40` from complete objects
in the verified transfer prefix. Both arms have identical observations/OCR
hashes and PREPARE_ROI -> READ_ROI -> WRITE_TEXT -> STOP actions. At step 2,
bounded retention offers 42 candidates and selects the earlier step-1 date
`11/08/2017`; current-only offers one incorrect current OCR candidate. The
actual written text scores 1 versus 0. The other memory win, selector loss and
selector bypass remain report-level interpretations pending complete raw
transfer; see `raw-trajectory-audit.partial.json`.

### Source-level inference

The frozen analysis first averages case differences within each source and
then gives each source equal weight. The source-weighted difference is +0.10, or 10 percentage points;
it differs from +2/84 because the two winning sources each contain one case,
while each development source contains five cases.

- All 80 pairs from the 16 development sources are ties.
- The four retention-validation source differences are `[0, 0, 1, 1]`.
- The prespecified 20,000-resample, role-stratified source bootstrap gives a
  one-sided 95% lower bound of **0.0**.
- The minimum source count and +0.05 rate-difference target (5 percentage points)
  are satisfied, but the
  required strictly positive lower bound is not.
- `numerical_benefit_threshold_met=false`; scientific acceptance remains HOLD.

Resampling four validation sources produces only zero-valued sources with
probability `(2/4)^4 = 6.25%`, explaining the zero fifth-percentile lower bound.
No post-outcome source weighting, cohort expansion or threshold adjustment was
applied. The degenerate two-ended `bounds` in the terminal contrast describe
missing-label bounds; they are not sampling confidence intervals.

The primary contrast has complete observed outcomes. Intermediate candidate
events can still be UNKNOWN, particularly when no usable decision anchor
exists. Those rows and their conditional-rate bounds remain in the reports;
they were not recoded as negative observations or removed.

## 2. Selector replication: positive overall, with a preserved loss

On 14 other source groups, public_rule succeeds in 21/54 cases and
frozen_neural in 13/54, a descriptive paired difference of 14.81 percentage
points. The 54 paired outcomes are 9 wins, 44 ties and 1 loss. Every primary
episode is evidence-verified and has an observed terminal outcome.

| Success category | Public rule | Frozen neural |
| --- | ---: | ---: |
| Initially correct no-op | 10 | 10 |
| Candidate-mediated delivery | 10 | 3 |
| Bypass delivery | 1 | 0 |
| Total | 21 | 13 |

After restricting to initially incorrect cases, terminal success is 11/44
versus 3/44; the public numerator still includes the single bypass success.

The loss is pair `f63a25fb9bbcebb0c93c`, case
`case-bee0bc299bb38ad94d80fd94`, source
`merchant-5c29904ee2eb4422e25f9030`. Both arms select a candidate judged correct
at the step-2 anchor and execute WRITE_TEXT. The public arm is classified as a
delivery failure. The evaluator's terminal condition also includes required
image quality and preservation of committed output, so this report alone does
not establish a wrong-text selection.

The public bypass win is pair `716b97bac5758ef3f2a5`, case
`case-e2393ca0b9c3d9ba481aca2a`, from the same source. It has no WRITE_TEXT action
but a correct final delivery. The total 21/54 must not be described as 21
successful candidate-text deliveries.

This replication supports retaining the public selector as the fixed research
control. It does not establish a memory benefit, universal dominance, or
production readiness. Sampling uncertainty for the selector contrast was not
estimated; 54 cases are not 54 independently authenticated sources.

## 3. Three memory layers and what was implemented

| Layer | Implemented scope | Evidence in this run |
| --- | --- | --- |
| Task working state | Episode-scoped candidate retention; empty start for a new task | 168 real actor episodes with fixed public selector |
| Episodic/source memory | SQLite authority; versioned facts, source/namespace filtering, dependency invalidation, bounded retrieval and delivery receipts | Separate 18-scenario fresh-process fixture suite |
| Slow semantic/skill consolidation | Contract only: future candidates require separate versioning and acceptance | No consolidation candidate implemented or evaluated |

The episodic authority makes updates and revocations visible to later controlled
reads. Old snapshots are filtered against current authority. Transitive
dependencies invalidate when a prerequisite changes. A namespace and a digest
provide separation and content consistency; neither authenticates an owner or
an independently maintained source timeline.

### Fresh-process mechanism suite

The frozen implementation runs three producer subprocesses and waits for each
to exit before its successors. Eighteen consumer subprocesses, with 18 distinct
observed PIDs, write real fixture delivery files. Seventeen scenarios open the
persistent authority; the persistence-off scenario avoids opening it entirely.
Consumer requests do not carry previous working state or expected answer text.
All 18 scenario checks pass, all embedded receipt hashes were independently
recomputed, and execution-source pins remain unchanged.

The suite covers on/off, retrieval off, delivery off, association absent/off,
exact lookup, BM25, uniform store replay, chronological context assembly,
updated facts, old snapshots, dependent invalidation, current-fact revocation,
wrong source/namespace and preservation of an unrelated flow.

These are deterministic mechanism checks with `model_calls=0`. They establish
the same-host, same-authority fresh-process read-to-file path. They do not
establish actual agent use, unseen successor-task benefit, a full owner cold
recovery, or independent trust-domain recovery.

The suite's `revoked_snapshot` reuses a snapshot already made stale by the prior
update. That row does not independently isolate revocation of the updated fact.
Direct current-fact revocation is demonstrated, and separate passing unit tests
cover direct active-fact/dependent revocation and fresh-CLI pre/post-revocation
reads of the same old snapshot. Preserve this distinction instead of rewriting
the frozen campaign after observing it.

### Baselines and remaining mechanism limits

Exact KV, BM25, uniform replay and chronological context assembly are preserved
as explicit strategies. In this fixture their relevant baseline scenarios each
have one eligible record, so their equal outputs are not comparative task
performance. BM25 plus file delivery is not a full RAG benchmark; chronological
record assembly is not an actual model ICL experiment; uniform record sampling
is not optimizer replay.

No neural association head is supplied or called. `unavailable` is distinct
from `association_off`; neither is a positive head-ablation result. Derived
cross-document facts are producer-authored fixtures. Similar-flow lookup uses
an explicit source allowlist. Genuine cross-document reasoning, flow selection
among competing sources, answer-level abstention and adversarial interference
remain unevaluated.

Deletion means exclusion from live logical payloads and later controlled reads.
It does not prove erasure from old snapshots, logs, backups, prior contexts or
model parameters. The live authority must remain current and trusted; rollback
of that authority and revocation at an external action commit barrier remain
open.

## 4. Costs and validation

Measured campaign wall time is 209.684 seconds for retention and 126.203 seconds
for selector. The mechanism suite reports 0.663 seconds wall time. These are
distinct campaign envelopes, not sums of overlapping nested measurements.

For retention, summed attempt CPU is 180.492 seconds with bounded memory versus
178.938 seconds with current-only memory. Summed attempt wall time is 186.965
versus 185.356 seconds. Every retention episode has these observed measurements;
summed episode wall time is not elapsed campaign time. Energy, provider charges
and complete end-to-end acquisition, storage, retrieval and recovery costs are
unknown. Full cost qualification remains open.

The final new targeted test set passes **35 tests**. It includes real OCR/Torch
actor-pair wiring, plan/cohort reconstruction, malformed/missing evidence,
selector-chain attribution, source-level inference, episodic invalidation,
retrieval controls and subprocess qualification. This is not a claim that every repository test passed.

An earlier development validation exposed a WorkingState attribute mismatch.
The correction is included in the frozen execution source. Original failed
development logs and the final passing logs are retained separately; the failed
development attempt is not one of the 276 prospective actor episodes.

Exact-source GitHub CI has its own timestamped checkpoint in `validation/ci/`.
Queued or unfinished jobs are pending, not passed. The code remains in six
reviewable stacked draft PRs; the result archive is a separate evidence stage.

## 5. Raw evidence and recovery boundary

The full run-output archive covers **10,365 files and 243,281,645 original
bytes**, including both actor campaigns, the mechanism producer/consumer
requests and responses, delivery files, SQLite state, plans, source capsule,
launcher and logs. No failed or unknown actor row was removed.

The content-addressed archive retains every path-to-byte binding while storing
duplicate content once: 7,122 unique objects, 149,046,627 unique bytes,
compressed to **61,412,948 bytes**. Its SHA-256 is
`f77acd9feb27fda3f8000b0d089dbdbe258a4adfb7acedcb2e0cd590cc4f361e`.
The manifest SHA-256 is
`3c7799846836a18b6a5470e03cda92919ede2fcf76c8ee9ede20ae0e945ce336`.

**Local full archive restoration is PENDING.** The h service returned
`-32603 Internal error` during transfer; even its non-host `effective_config`
probe failed. The same-version checkpoint preserves 371/938 verified chunks,
24,313,856 bytes: a 24,117,248-byte continuous prefix plus three later chunks.
The first missing offset is 24,117,248. `ARCHIVE_INDEX.json` binds every
published binary part and both missing ranges; `TRANSFER_CHECKPOINT.json`
retains the original per-chunk receipts and errors. These partial bytes are
not a complete archive, and no successful `RESTORE_RECEIPT.json` exists.

Published binary parts remain below the repository's 512,000-byte per-blob
limit; the policy is unchanged. `restore_archive.py` requires the full pinned
archive before creating a destination and verifies every restored file. Its
small-fixture checks do not stand in for the unfinished full restoration.

The archive contains the original actor outputs and frozen execution source.
External runtime dependencies, the complete original material collection and
the full owner/effect state are not bundled. Byte reconstruction is not an
offline rerun of the entire system, owner recovery, or independent source
authentication. The previous MEM5 second-host archive milestone also does not
close those owner/effect requirements.

## Outstanding decision gates

`BLOCKERS.json` is the current result ledger. The frozen `../ACCEPTANCE.json`
remains the pre-execution requirements document, not a mutable outcome report.

The next scientific gate requires a separately frozen predecessor-experience
to unseen-successor-task experiment through the actual agent/tool entry,
matched on/off plus the four baselines, meaningful competing sources and
content removal/replacement counterfactuals. A real association component,
independently authenticated authority/recovery, complete applicable costs and
required exact-source CI are additional open gates. None can be substituted by
more memory files, this fixture pass, or a change of labels in the ledger.
