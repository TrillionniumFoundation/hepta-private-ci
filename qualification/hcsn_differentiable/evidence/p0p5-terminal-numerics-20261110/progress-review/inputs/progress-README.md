# C2 complete-epoch progress and independent-audit preparation

This immutable appendix advances the [first-step launch snapshot](../p0p5-c2-launch-20261110/README.md)
without rewriting it. The training observation is **2026-11-10 22:00:42.152837 UTC**.
Five of the original six C2 fits were still active; one producer had completed.
The original job, source, roster and budgets are unchanged. Later observations
must be recorded separately. [STATUS.json](STATUS.json) states the exact scope.

## Observed training progress

The [first complete-epoch observation](observations/first-epochs/payload/SUMMARY.json)
and [later observation](observations/at-220042/payload/SUMMARY.json) retain the
original small JSON records and transport receipts. These observers did not
read full model tensors or growing probability arrays. The later
[handoff](observations/at-220042/HANDOFF.json) records:

| Seed | Learning rate | Complete epoch | Strict best D macro-F1 | Best epoch | Observed state |
| --- | --- | ---: | ---: | ---: | --- |
| 101 | 0.001 | 54 | 0.2399445918 | 52 | Active |
| 101 | 0.003 | 55 | 0.3607702975 | 54 | Active |
| 211 | 0.001 | 54 | 0.2687776898 | 52 | Active |
| 211 | 0.003 | 50 | 0.3910932361 | 40 | Producer completed |
| 307 | 0.001 | 54 | 0.2043634951 | 54 | Active |
| 307 | 0.003 | 54 | 0.3350217497 | 52 | Active |

These are individual, D-selected best scores from incomplete continuations.
They are not a new common-learning-rate selection, a held-out result, or a
sufficiently trained six-fit comparison. In particular, a latest-epoch score
must not be substituted for the journal's strict best score.

## First actual terminal fit: unchanged selected quality

For seed211 at learning rate0.003, the [original fit result](first-terminal/payload/fit/result.json)
reports `completed_development`, `development_plateau`, and producer training
adequacy, with 50 cumulative complete epochs and 36 new main updates. The
[original outer result](first-terminal/payload/outer/RESULT.json) records a real
zero exit status. Its selected best remains epoch40, the original checkpoint
with identical selected D metrics: macro-F1 `0.3910932361454862`, accuracy
`0.702272158237356`. This continuation therefore supplies no selected-quality
improvement. Producer adequacy awaits the independent terminal audit.

The [cost addendum](first-terminal/COST-SCOPE-ADDENDUM.json) distinguishes the
clocks. Original parent full outer wall is `14376.949902404798` seconds. The C2
child was reaped after `1266.1501302358229` seconds; its complete attempt wrapper
cost `1266.1814752598293` seconds. The cumulative complete-attempt cost is
`15643.131377664628` seconds. The extra `0.031345024006441236` seconds is charged,
not discarded or retroactively distributed into earlier epoch event times.
C2 child wait4 CPU is `1263.453444` seconds. Exact original exit CPU and therefore
exact cumulative CPU remain unknown.

The [original terminal metadata archive](first-terminal/hcsn-c2-first-terminal-metadata-20261110-v1.zip)
contains complete small records, not full checkpoint or posterior arrays.
Its [control archive](first-terminal/control-plane-originals-v1.zip) retains two
120-second binary-read RPC timeouts and the subsequent bounded read-only
archiver. Those control-plane failures did not rerun or restart training.

## Frozen independent terminal auditor: prepared, not executed

The [program ZIP](terminal-auditor/preparation/program.zip) is 73,473 bytes,
SHA-256 `87bedabde7f37ec8d70a80305691f1116e80493174a5cd33bf7058f635230b3a`.
The [program manifest](terminal-auditor/PROGRAM-MANIFEST.json) is
`4cc126ad4cf11e12c80408a868f8c673be70bccdce95a02228fda9d1543ef8d2`;
the [plan](terminal-auditor/PLAN.json) is
`1fc0d941bc9d96544c8caa5740aaba130685fed74b620f6e62dc22bec4a715ad`.

Its fixed total envelope is 1,800 seconds, one worker and one thread. Metadata
and trace audits share the first 360 seconds; each full-D replay has at most
210 seconds and is also limited by the remaining total budget. The 60-second
finalization reserve is inside the envelope. RSS is limited to2GiB. No optimizer
restoration, training update, numerical oracle or confirmation-E read is allowed.

Execution requires all six real terminal attempts, absent or zombie worker PIDs,
the immutable controller result, and the original durable native terminal
receipt. A caller assertion alone cannot open that gate. A controller that never
finalizes yields HOLD under this version; the plan does not silently create a
postmortem substitute. Actual input binding and a separate root execution
decision are still required.

The auditor independently checks epoch commits, strict-best and plateau logic,
resume witnesses, real gradient-enabled trace records and their completed-step
links, checkpoint identities, and full D predictions. A supplemental no-grad
trace remains separate from actual training visits. The all-six replay admission
is required before choosing a new common learning rate. Reproduced quality,
independent adequacy and numerical qualification are separate outcomes.

The [preparation summary](terminal-auditor/preparation/SUMMARY.json) retains all
earlier source/test attempts, the original failed fixture, independent negative
examples, and their closure. Final validation passes 28 synthetic tests and help
output. This validates the prepared checker within that synthetic scope; no
actual C2 checkpoint or trace has yet been independently audited.

## Resource analysis and confirmation E remain separate proposals

The [resource plan](resource-plan/PLAN.json) was fixed after C2 launch, early
complete epochs, and notification of the first producer terminal. It is not an
experiment preregistration. The historical 300/900/1800-second views remain
unchanged. The proposed later terminal view retains all seven cores, both
learning rates, all three seeds, failed fits, discarded partial updates and
whole attempt costs. No missing seed can be dropped to admit a common rate.
The target macro-F1 remains0.30; only complete-epoch crossings are observed.
Energy, billing and exact missing CPU totals stay unknown.

The [independent plan review](resource-plan-review/REPORT.md) found no blocker,
with one explicit clock rule: earlier quality-event clocks use parent full outer
plus child prefix; the final bill uses the full attempt wrapper. The final
wrapper tail must not be retroactively added to earlier target-crossing times.
This resource analysis has not yet been implemented or executed.

The [E candidate](confirmation-E-proposal/PROPOSAL.md) and
[interface review](confirmation-E-interface-review/RESULT.json) are unexecuted.
The original formal protocol calls for12configurations times3tuning seeds and
five fresh confirmation seeds. The present two-rate, three-seed study does not
complete that recipe. A possible independent subject-E evaluation of already
trained models would be a separately named one-shot scope, not formal fresh-seed
confirmation. Its suggested budget is unallocated and cannot consume the
terminal auditor's envelope. E remains unread; there is no automatic permission
to spend that confirmation opportunity after a favorable D result.

## Exact prior source and CI status

The [publication records](publication/api-progress.json) bind local commit
`a143bfda5036a54ed87afe21d184b5a9749fa0ee` and remote source
`7351e1a2c60e318686d3c01372acbde149af4432` to the same complete tree
`772cbf882db520525d6fa5c805c296aa2e8b97eb`. [PR5856](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/5856)
is a draft based on the preceding draft branch; no main merge or release
publication was performed.

The [exact local integrity result](prior-head-checks/worktree/RESULT.json) checks
eight manifests, 1,255 files, 66 directly stored ZIPs and 362 relative links, with
zero errors. The separate [committed-blob proof](prior-head-checks/committed-blobs/RESULT.json)
verifies 1,273 distinct regular files in that prior commit. Neither historical
proof covers this later appendix.

The [original API observations](ci/observations-original.zip) report scientific
PR run42907725860 attempt1 successful at that source; its artifact was not
downloaded for this observation. Codespell and blob-size jobs in blocking
run42907726032 succeeded. Contract, cargo-deny and several Windows jobs failed;
other jobs were still active. These observations do not establish repository-wide
CI success or explain failure causes from job names.

The [spelling red/green records](prior-head-checks/codespell-red-green.zip)
preserve the narrow additional exclusion of the exact immutable historical
failed spelling stdout, which contains the same five original false positives.
No scientific evidence bytes or thresholds were changed. The raw failure and
successful check remain available, together with their execution costs.

## Integrity, costs and scientific limits

[MANIFEST.json](MANIFEST.json), [ARCHIVES.json](ARCHIVES.json) and
[COPY-RECEIPT.json](COPY-RECEIPT.json) bind original bytes and copied inputs.
[COSTS.json](COSTS.json) points to full process, nested phase and unknown scopes.
The uploader [source-only review](publication-preparation/root-static-review/RESULT.json)
is preparation, not a publication receipt. The short
[cloud read interruption](publication-preparation/root-static-review/CLOUD-READ-INTERRUPTION.json)
occurred before process creation and did not affect native training.

Whole-training numerical admission and comparative scientific benefit remain
HOLD. The original numerical audit is a different bounded job; its later
terminal findings require their own evidence. P5 remains conditional on a
demonstrated benefit. No model, oracle, confirmation dataset or CI job was rerun
to assemble this appendix.
