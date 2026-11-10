# Resource curves, six full-D replays, and retained training-state coverage

This frozen follow-up records completed evidence. It does not admit HCSN as a
sufficiently trained winner, qualify the entire training trajectory, or declare
all repository CI green. The [status](STATUS.json), [cost ledger](COSTS.json),
[asset identities](assets.json), and [byte manifest](MANIFEST.json) keep those
decisions separate. Earlier snapshots remain unchanged in the
[original index](../p0p5-20261110/README.md) and
[terminal follow-up](../p0p5-followup-20261110/README.md).

## 1. What the recorded resources support

The [full report](resource-analysis-v1/output-v1/REPORT.md) gives both the original
42-attempt view and a distinct view adding seven C1 continuations. The
[analysis plan](resource-analysis-v1/PLAN.json) was frozen after terminal scores
were known; only the 300/900/1,800-second cuts and F1 target .30 were prospective
in the original campaign. No extra model evaluation was used to build curves.

All 49 report hashes bind to retained original or independently audited reports.
There are 2,927 complete-epoch observations and 42 explicitly timed
before-training evaluations. All 2,969 confusion matrices reconcile; the largest
macro-F1 difference is 1.11e-16. All 351 C1 early/late clock brackets reconcile.
The [independent review](independent-resource-review-v1/REVIEW.md) uses a separate
implementation and exact rational confusion-matrix arithmetic. It agrees on 56
budget/core/view rows and 336 candidate entries.

| Core | Original 300 s | Original 900 s | Original 1,800 s | Terminal D F1, including separate C1 | Selected adequate |
| --- | ---: | ---: | ---: | ---: | ---: |
| GRU | .4250 | .4250 | .4250 | .4250 ± .0112 | 3/3 |
| CfC | .3490 | .3490 | .3490 | .3490 ± .0161 | 3/3 |
| Surrogate PLIF | .1500 | .1500 | .1500 | .1500 ± .0323 | 3/3 |
| Event-time LIF | .1841 | .3130 | .3130 | .3130 ± .0419 | 3/3 |
| S4D-Lin | .3597 | .3597 | .3597 | .3669 ± .0243 | 3/3 |
| Causal attention | .4026 | .4026 | .4026 | .4026 ± .0487 | 3/3 |
| HCSN, budget-censored | Missing | .0256 | .1086 | .3576 ± .0318 | 0/3 |

The mean uses all three seeds at one common LR selected from .001 and .003;
all defined cells select .003. Both LR rosters are preserved. The ± term is
sample SD, not a confidence interval. Missing observations are not zero and are
not interpolated. None of the six HCSN candidates completed an evaluation by
300 s. At 900 s, the selected HCSN roster includes two complete-epoch results
and one timed before-training evaluation. Startup and diagnostics consume the
same at-most per-fit process-wall ceiling; this is not an energy-matched budget.

At target F1 .30, the median first observed complete-epoch crossing is 9,586.993 s
for selected HCSN, versus 55.594 s for GRU. These are observation times, not exact
continuous crossing times. The complete six-candidate process-wall sum is
86,261.115 s for HCSN and 784.263 s for GRU, including the separate C1 additions
where applicable. Historical tuning, failed probes, controller work, audits and
transport remain additional, separately scoped ledger entries. Complete-attempt
maximum RSS is 3.795 GiB for HCSN and .762 GiB for GRU; neither is a measurement
of memory at target crossing or GPU VRAM. Energy is unmeasured.

The [complete results](resource-analysis-v1/output-v1/RESULT.json) retain every
selection, missing value, censoring flag, cost and original clock convention.
The [compact points](resource-analysis-v1/output-v1/POINTS.json) retain all 2,969
observations. The two parts in `curves-originals/` concatenate into the exact
original 966,326-byte ZIP, SHA256
`0ab09b443b102e056849900eb2fcb2d20933a78d6ef321373ae354f98e9b5f1d`.
The [reassembly receipt](CURVES-REASSEMBLY.json) verifies every original member,
including the full 5,799,157-byte confusion-matrix input. Recompression is not
needed. Producer source is also available in
[the source directory](../../../../proposals/localization-v3/resource-analysis-v1/README.md).

![Recorded quality and charged process costs](resource-analysis-v1/output-v1/RESOURCE-COMPARISON.png)

## 2. Six best checkpoints reproduce the entire development set

The [full-D summary](full-d-replay/SUMMARY.json) and
[review](full-d-replay/REVIEW.md) cover all six HCSN candidates, including the
lower-performing LR.001. Each fixed strict-best checkpoint was evaluated afresh
on all 128 subject-D windows and 31,952 valid events, using the exact v8 source,
original common frontend/head, fixed physics and CPU FP64 runtime. Every
confusion matrix is identical; the largest metric difference is 2.22e-16,
within the predeclared 2e-12 gate. Checkpoint, data, source and physical tensors
are bound before and after. New logits, labels and source-row ordering are
archived. No optimizer was constructed, restored or stepped by this replay;
loading a checkpoint can deserialize unused optimizer/RNG fields.

The replay controller took 730.309 s and 735.747 CPU seconds including its
descendants. The enclosing bootstrap also includes native validation and
extraction, so it must not be added to the controller time. All stage,
validation, archive and publication costs remain in the
[nested ledger](full-d-replay/COSTS.json).

This is reproducibility on the same development subject already used for
tuning. It does not establish scientific generalization or repair incomplete
training: all six original HCSN attempts remain budget-exhausted and
inadequate under their stopping criterion. Subject E remains unscored.

## 3. Original training traces retained no post-update states

The [original-label scan](trace-coverage/recovery-v1/RESULT.json) reads the actual
retained training trace bytes and binds their hashes. Its
[independent JSON/order review](trace-coverage/independent-review-v1/REVIEW.md)
reconstructs the effective-batch32/microbatch8 order without importing the
producer. It does not independently reread the large probability arrays.

Across six fits, the retained 2,066 record slots contain 16,492 valid
sample-position-layer states. Every original `update_index` is **0**.
The main phase and epoch 1 are derived from the exact original epoch journal,
manifest order and runner; they were not literal epoch labels in the raw trace.
Per seed, both LRs retained 346/343/344 slots and 2,750/2,744/2,752 valid states.
Only about .0649%–.0660% of reconstructed seen valid states were retained per
fit. The reconstruction reconciles each capture count, seen-slot count and
excluded-padding count; dropped probability states cannot be recovered from it.

Post-update retained record slots and valid states are both **zero**.
Replaying a terminal checkpoint creates supplemental evaluation visits; it
cannot turn these old traces into observations along the optimization path.
Whole-training numerical admission therefore remains HOLD. The ongoing
terminal numerical audit and prospective C2 recording policy are separate
follow-ups and are not claimed complete by this package.

## 4. Published source chains and CI have separate outcomes

An actual publication defect omitted 15 ignored log files from committed Git
objects even though they existed in the worktree and frozen manifests. The
[retained failure](publication/committed-evidence-recovery-checks-v1/original-missing-logs.json)
finds all 15; the
[repaired-tree check](publication/committed-evidence-recovery-checks-v1/recovered-trees.json)
verifies all 785 manifest members. Exact original bytes were force-added;
neither the old logs nor frozen manifests were rewritten. The
[timing/source-scope addendum](publication/committed-evidence-recovery-source-scope-addendum-v1.json)
states the limits of the earlier wrapper. The later
[CURRENT closure](publication/committed-current-evidence-closure-v2/RESULT.json)
checks 794 distinct committed blobs at local revision
`7f0d842eaee4afc01a769a8e37be0bae2d9835bc`, tree
`4bb4995c3c1058d268c032a0d15cdfe9297a6ff8`, with explicit pre/post hashes.
These checks precede this new package and do not certify a future commit.

Hosted science run **42890048946**, attempt 1, succeeded for source head
`cd3b7ac49294174a98e02636247615534c19bd89`, tested merge
`f63b067ac577a6eea363c37d1358f65dc7b4f4ba`, and that same tree. Its
[original artifact](publication-and-science/science-run-42890048946-attempt1-artifact-13797877354.zip)
is retained byte-for-byte: 77,859 bytes, 14 members, artifact **13797877354**.
It contains 92 science tests, four historical error budgets, the four-manifest
785-file integrity check, three QVI tests, three control tests and source/index
immutability. Those scopes are not expanded into training-domain qualification.

The [CI observation](ci/hcsn-ci-current-head-observation-v1.json) and
[job details](ci/hcsn-ci-failure-and-current-jobs-v1.json) preserve their own
observation times. The earlier source-PR blocking run **42849616115** failed:
retained Windows logs show a filename-too-long checkout failure, and the
contract log shows a README readiness-discovery-link gate failure. Two other
job-log retrievals failed; their causes remain unestablished. This does not
attribute the earlier failures to an unobserved later head. Overall repository
CI is not declared green. Connector-decoded logs and retrieval errors remain
in the [log ZIP](ci/current-ci-decoded-logs-v1.zip); its exact provenance is in
the [copy receipt](BASE-COPY-RECEIPT.json).

## 5. Archive and reproduction boundaries

The new complete full-D payload is draft-release asset **732788592**, 19,144,412
bytes, SHA256 `ff41e5ef909708a5c2472f6786d0e82b6d69a80d968047de2746bcaf84daaac5`.
All 254 members and an authenticated full readback passed. Original models
remain bound to the earlier fully verified asset **732598130**. The release
remained draft/prerelease with `published_at=null`; anonymous probes returned
404. The first publication attempt failed on unsupported `gh --slurp` before
an upload; the distinct second attempt uploaded the same ZIP once. Both
attempts, including original command outputs, are retained in
[publication originals](publication-and-science/full-D-publication-originals-v1.zip).

The prior 28 verified payloads and this additional verified payload account
for 29 known payloads with full authenticated readback. This is not a fresh
count of all release API entries. The old metadata-only preliminary asset and
failed starter upload keep their old limitations. No release was published or
main branch merged.

For local integrity, run `qualification/hcsn_differentiable/evidence_chain.py`
with this `MANIFEST.json` and this README. Relative links and ZIP CRCs are
integrity checks; scientific decisions require the bound plans and original
results. [COSTS.json](COSTS.json) links exact timing receipts, retains failed
attempts and unknown scopes, and intentionally provides no fabricated total
energy, currency or additive grand runtime.
