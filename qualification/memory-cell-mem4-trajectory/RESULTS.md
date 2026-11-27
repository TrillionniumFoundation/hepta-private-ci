# MEM-4: complete native trajectories, matched replay exposure

Scientific decision: **HOLD / NoUpdate**. Keep uniform replay as the research
default. Structured ordering has no consistent advantage in this experiment.

## Actual execution

The [native job](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/42742934161/job/129588167161)
completed successfully on source `ae04c09921a600b5ccb82fe72a631e32146856bc`,
tree `233bdc60b6483f19e2e826488973c521875b178a`. The checkout remained clean
and unchanged. This run built the existing Rust example from the complete locked
workspace, with Rust 1.96.0 and Python 3.12.16. It did not reuse the missing
MEM-2 executable or a transformed minimal workspace.

The new debug binary SHA-256 is
`fa3426e85164765a920aaa69db74c5ebc4bab712b0358734d08beb5be4355f4b`.
The [independent readback](observations/independent-audit.json) checks all twelve
Python source identities and 47 files in the native compilation closure against
the executed inventory and published source. The inventory records 66 files,
including tests and other entries outside this compilation closure.

All **30/30 trajectories** completed: five seeds, dynamic/stationary conditions,
and one independent no-replay reference plus two replay arms in each cell.
All **10/10 matched pairs** passed. No run or failed pair was omitted.

## Retention and plasticity

B-stage stable-A probes are the descriptive retention comparison. Each replay
arm contributes eight stable-A probes per seed, forty per condition.

| Condition | Uniform | Structured | Structured minus uniform |
| --- | ---: | ---: | ---: |
| Dynamic owner | 34/40 (85%) | 35/40 (87.5%) | +2.5 percentage points |
| Stationary owner | 36/40 (90%) | 30/40 (75%) | -15 percentage points |

B prequential accuracy is 83.75% for both dynamic arms. Stationary uniform is
81.25%, versus 81.0417% for structured. The complete per-seed and other-panel
outcomes remain in the raw archives. These are five synthetic stream seeds,
with one fixed encoder/kernel; they are not forty independent source groups,
independent training repeats or real-task confirmation.

MEM-2 branched separate replay windows from common parents. MEM-4 carries the
stationary trajectories through A1 → B → A2 without that window reset. Dynamic
owner cuts retain their prescribed reset/rebuild semantics. All ten A1 pre-state
identities match; B pre-state identities differ. Those hashes also bind lineage
and cannot alone establish differences in numeric weights, particularly after
the dynamic reset. Similar aggregate rates to MEM-2 are not additional
independent evidence from new seeds.

## Matching, recovery and cost

Independent reconstruction read all twenty replay trajectories and forty replay
windows. It rebuilt source/version support, selected order, request bytes and
hashes, the fixed kernel-work formula, and all 2,560 replay updates from retained
plans, reference populations and event receipts. All 1,800 probe outcomes were
recomputed against seeded current truth. All forty candidate checkpoints and
ninety worker-recovery checkpoint hashes matched their retained witnesses.

The entire campaign contains 7,200 online updates, 120 owner-rebuild updates,
2,560 replay updates, 7,200 prequential observations and ninety worker restarts.
Recovery leaves the Python owner alive; this does not qualify full-owner cold
recovery, continuous version transitions or unlearning.

Both arms receive identical full replay-record multisets, coverage, payload and
update-request bytes, update counts and logical native work. Their public
priorities come from the independent no-replay reference. The reference is
executed once per condition/seed, while each arm is conservatively charged its
complete reported cost. The audit separates actual totals from these two arm
accounts; it does not count shared reference execution twice in actual work.

Actual work across all thirty trajectories totals **6,298,880 native kernel
multiplications**. Across five seeds, each dynamic arm plus its full reference
is charged 2,027,520; each stationary arm plus its reference is charged 1,994,240.
CPU, wall time, calls, IPC and owner checks are reported separately and are not
physically equalized. Trial-summary wall times sum to 12.952432191 seconds; the
native build separately reports 18.36 seconds. These exclude setup, independent
readback and packaging, and are not a complete physical lifecycle cost.

## Preserved evidence and validation

[The archive index](observations/archive-index.json) covers all 543 original
Actions artifact members, with no omissions. Every repackaged member was reopened
and verified for size and SHA-256. The three archives are below the unchanged
512,000-byte asset limit. Original source/build/cost/failure records are retained;
the original artifact did not include an ELF. Artifact SHA-256 is
`2bbe72b935a2c23cf76d4064d659f9085c9369e79ec5c538c230d47664aad076`.

Five normal and five optimized software regressions passed before formatting;
tested ASTs are preserved. The [exact-source MEM CI](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/42742311910/job/129586101229)
passed 42 tests, including the five trajectory contracts. The
[CI readback](observations/ci-readback.json) separates that source from the later
native execution head. These results do not claim whole-repository CI success,
executor authentication, neural superiority or production qualification.

The remaining MEM priority is a fixed-support selector comparison with
independent real-task confirmation. The existing candidate campaign still has
no terminal memory gain; the later bound crop diagnosis and no-op/UNKNOWN
denominators remain part of its interpretation.
