# Post-snapshot terminal and verification evidence

This package follows the [472-file evidence snapshot](../p0p5-20261110/README.md).
That snapshot's manifest remains exactly
`bc8721b37d4a69c28a25a028dd6375ebbeaaa41111bafc97a22b7239609f5bc6`.
Its original-HCSN observation was at 18:01 UTC; it was curated at 18:36 UTC.
Later terminal results and recovered receipts do not rewrite that observation.

**All 42 original attempts are terminal. The six HCSN attempts exhausted their
declared budgets; none established the training-adequacy condition.** Completed
execution, source integrity, numerical qualification and scientific benefit
remain different claims. Development subject D was used for selection; E was
not scored by this work.

## Claim-to-original map

| Claim | Exact evidence and limit |
| --- | --- |
| Frozen snapshot integrity passes | [Independent result](review/final-curation-delta-review-v2/execution/RESULT.json), [review](review/final-curation-delta-review-v2/REVIEW.md), [capsule](review/final-curation-delta-review-v2.zip): 472 files, 38 archive instances, 182 relative links, 55 cost references and 245 explicit bindings |
| Continuum drift wording is corrected | [Narrow closure](review/current-continuum-scope-closure-v1/RESULT.json), [review](review/current-continuum-scope-closure-v1/REVIEW.md), [before/after capsule](review/current-continuum-scope-closure-v1.zip); this does not grant a finite QPR chain the continuum's long-run law |
| Late complete baseline/C1 aggregates agree with the previously reviewed small files | [Original aggregate ZIP](review/baseline36-c1-aggregate-originals-v1.zip), [byte receipt](review/baseline36-c1-aggregate-originals-v1-receipt.json), [independent addendum](review/c1-aggregate-originals-addendum-v1/execution/RESULT.json) |
| Baseline metrics, clocks and common-LR selection were independently recomputed | [Original recomputation](review/c1-clock-outcomes-independent-review-v1/RESULT.json), [review](review/c1-clock-outcomes-independent-review-v1/REVIEW.md); 351 C1 clock intervals and 43 confusion matrices, without a new model forward |
| Original42 has a real terminal result | [Controller result](original42/terminal-small/campaign-v2/RESULT.json), [complete launcher](original42/receipts-v1/launcher-final-original.json), [18:51 observation](original42/native-hcsn-terminal-20261110-1851-v1.json) |
| Six HCSN attempts are budget-censored | [Terminal summary](original42/receipts-v1/HCSN-TERMINAL-SUMMARY.json), [six original reports and context](original42/receipts-v1/hcsn-fresh42-terminal-small-20261110-v1.zip), [copy identities](original42/receipts-v1/COPY_LIST-v2.json) |
| All42 originals, including failed and partial work, were archived | [Archive receipt](original42/receipts-v1/archive-original-receipt.json), [archiver source](original42/receipts-v1/archive_fresh42_completed_v1.py); full member inventory is retained inside the small handoff ZIP |
| Nine new original42 archives have complete authenticated byte readback | [Uploader result](original42/receipts-v1/upload-RESULT.json), [uploader source](original42/receipts-v1/upload_fresh42_completed_v1.py); no overwrite or release publication |
| Two independent baseline/C1 review archives and the native attention profile have complete readback | [Original uploader result](publication/review-profile-assets-v1/RESULT.json), [terminal status](publication/review-profile-assets-v1/terminal-status.json); actual upload ended at 18:06:57 UTC and its complete receipt was recovered later |
| Terminal numerical cases were fixed independently of model inspection | [Plan](plans/final-hcsn-numerical-plan-v1/PLAN.json), [exact capsule](plans/final-hcsn-numerical-plan-v1.zip), [independent static review](review/final-hcsn-plan-independent-review-v1/RESULT.json); a plan is not an executed numerical pass |
| Repaired CURRENT and existing links pass the integrity checker | [Original result](verification/evidence-integrity-current-closure-v1.json), [process/input receipt](verification/evidence-integrity-current-closure-v1-receipt.json); this is the explicitly hashed pre-terminal-update CURRENT, not every future revision |

## Original42 terminal outcomes

The original controller completed the declared roster with 26/42 attempts
meeting its diagnostic-plus-plateau heuristic. Those are 26 of the 36 baseline
attempts. Seven baseline epoch-cap attempts later passed the separately declared
C1 extension, giving **33/36 baseline chains**. Three memorization failures
remain. The original controller result is not retrospectively changed to 33.

All six HCSN diagnostics passed. Main training completed 46 or 47 full epochs,
then returned a handled resource-budget failure with code 2. The recorded inner
wall exceeds the soft limit and peak RSS stays below the declared RSS limit.
No HCSN report records a plateau stop or adequate training. Partial-epoch work,
its interrupted checkpoint and its complete process cost remain in the archive.

| HCSN candidate | Complete epochs | Strict-best epoch | Best observed D macro-F1 | First observed D F1 >= .30, process seconds |
| --- | ---: | ---: | ---: | ---: |
| seed101, LR .001 | 46 | 46 | .225177175 | Right-censored |
| seed101, LR .003 | 47 | 47 | .353904163 | 9,586.9940 |
| seed211, LR .001 | 46 | 45 | .244923402 | Right-censored |
| seed211, LR .003 | 47 | 40 | .391093236 | 7,269.0275 |
| seed307, LR .001 | 46 | 46 | .159200225 | Right-censored |
| seed307, LR .003 | 46 | 43 | .327756295 | 9,690.4187 |

These are original recorded complete-epoch metrics. The failed reports have no
final `selected_development` evaluation or saved final development-logit artifact.
The best epoch must be located in the complete epoch records; the last epoch
is not a substitute. Independent fresh full-D replay is a separate task.

The LR .003 three-seed mean is .3575845645 with sample SD .0318284630.
The LR .001 mean is .2097669341 with sample SD .0448912285. The descriptive
common-LR choice is .003, but **zero of its three seeds is adequately trained**.
Its median first observed .30 crossing is 9,586.9940 seconds. A first observation
is not the exact unobserved crossing time, and D is tuning data.

The six original trace files retained 343--346 records each before reaching
their byte budgets, out of 537,856--547,072 seen record slots. They are
chronological prefixes and explicitly truncated. Record slots are not identical
to valid sample-position states; no population coverage estimate is inferred
from those counts. Final-checkpoint replay cannot repair the missing historical
optimization-time trajectory. Full training-domain numerical admission is HOLD.

## Costs and archival scope

[COSTS.json](COSTS.json) extends the [earlier ledger](../p0p5-20261110/COSTS.json).
Enclosing and nested timings are never added. The original controller records
14,378.056994 seconds of wall time, 95,769.851164 summed fit-process seconds,
95,753.221092 child CPU seconds and 141.524450 controller CPU seconds. Summed
fit durations overlap in calendar time. The six HCSN fits contribute
86,261.115410 process seconds inside that original42 total.

The complete outer launcher additionally encloses source extraction and the
native thirteen-test child. It records 14,383.004945 wall seconds and
95,899.502808 child CPU seconds. Those totals already include the campaign
controller and its descendants; they must not be added to the nested fields.
The exact original launcher and per-fit outer receipts govern the cost scope.

Original42 archive construction, two independent review phases, the later
aggregate recomputation, profile packaging and authenticated upload/readback
are separately retained. All failed attempts stay charged. Unknown physical
energy, GPU VRAM, complete host reservations, provider charges and unmeasured
historical work remain unknown, rather than zero.

[assets.json](assets.json) binds 28 payloads to retained authenticated full-byte
readback. The independently observed API lists an additional preliminary JSON
manifest with metadata only and the incomplete official-data `starter` asset.
The starter's declared size is not proof of uploaded bytes. No asset is deleted
or replaced, and the release remains an unpublished draft. The repository is
public; accessing the raw draft assets requires appropriate authentication.

## Reproduction and source identity

The [handoff index](review/HANDOFF.json) identifies each independent review
capsule. Original source and report bytes are retained without reformatting.
The delta review imports an earlier helper; its exact separately retained
[helper source](review/final-curation-independent-review-v1/review_final_curation_v1.py)
is bound in that review's execution receipt.

To reproduce historical document checks, use a disposable repository checkout
and the capsule's exact CURRENT before/after bytes. The frozen delta review
checked the before-closure document; the narrow closure checked the declared
replacement and its unchanged companion inputs. Running that historical check
against a later CURRENT is a different input, not a reproduction failure.
Keep the sibling capsule directory names when reconstructing the review layout;
retained execution receipts contain the original arguments and paths.

Embedded manifests describe their archive members or their original execution
directories. Treat them as opaque files in the top-level evidence manifest;
do not feed them to the repository checker as if their paths were relative to
this package. Verify downloaded archive bytes, CRC and member hashes before
replaying their source. Large original model/log archives are referenced by
the authenticated draft-asset receipts, rather than replaced with summaries.

The [numerical plan review](review/final-hcsn-plan-independent-review-v1/REVIEW.md)
checks all 13 pinned v8 source files, six exact episodes and fixed future-gap
lists. It defines 54 best-checkpoint finite cases plus six last-checkpoint
diagnostics. Its final execution wrapper, native launch and numerical results
belong to separately bound execution evidence. Neither the plan nor this
terminal/archival package grants a numerical pass.

## CI and research admission

The [later CI observation](publication/hcsn-ci-observation-followup-v1.json)
records the architecture workflow succeeding for source PR5803 while its
blocking workflow remained queued. New evidence/protocol branches had their
own queued or running checks. Earlier science fixtures and source-tree
identities remain in the frozen snapshot; they do not certify later changes.

The [evidence draft PR](publication/hcsn-evidence-pr-created-v1.json) and
[protocol draft PR](publication/hcsn-protocol-pr-created-v1.json) have exact-tree
publication receipts. No main-branch merge or release publication is part of
this evidence package. Training adequacy, numerical-domain qualification,
independent confirmation, optimal-boundary benefit and physical efficiency
remain separate gates.
