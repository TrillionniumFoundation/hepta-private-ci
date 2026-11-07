# Fresh WSP confirmation: implementation and negative efficacy result

One new, locally frozen experiment completed. It used five existing training
fits, all 320 original TRAIN worlds, 100 finite path candidates, and 320 newly
generated confirmation schedules. The new schedules were generated only after
all candidate files were frozen. All 2,880 paired confirmation executions and
6,400 TRAIN path/world executions independently replay with maximum metric
difference **0**. No new model qualified for production adoption.

## Sources and scope

The task, arithmetic, checkpoint features, complete original TRAIN and evaluator
remain owned by `wsp_native_value_20261105/value_edit`, based on commit
`5669aa349fde9eb0b6692dbfaa55a1b9897f6e69` (PR4840). Executed new source is
identified by `PROTOCOL_FROZEN.json` and source commit `8db5c6e`; commit
`29a79d2` additionally contains the frozen protocol. These hashes and file bytes
remain the authority even when a later ledger fix is reviewed.

The task is finite deadline-sign prediction. It is not a financial Call/Put
experiment, live Trader test, new training-fit replication or complete-network
training comparison. Five existing fits remain the inferential unit. Content
exclusion covers 2,896 known historical schedules, not unknown external trials.
The local event chain and SQLite ledger do not constitute an independent data
authority or external preregistration.

The complete-replication direction already excluded by exact necessary-ranking
certificates was not fitted again. The new A proposal tests a different,
restricted one-step objective. No new missing-state proof was found; a smaller
hidden layer alone does not establish information loss.

## Frozen arms and results

| Arm | Operation | IID utility | OOD utility |
| --- | --- | ---: | ---: |
| C | unchanged checkpoint | 0.2477093826 | 0.1117550349 |
| L | literal execution fidelity; no invented repair | 0.2477093826 | 0.1117550349 |
| E | terminal-anchored analytic edit | 0.2514629791 | 0.1159549800 |
| G | matched projected-gradient solve | 0.2514629791 | 0.1159549800 |
| A | Agent-proposed supported-spectrum edit | 0.2506933512 | 0.1051185147 |
| EG | selected edit plus 32 stateless gradient steps | 0.2487937727 | 0.1130185110 |
| R | single stored L2/Linf-matched random edit | 0.1670759629 | 0.0849989730 |
| MYOPIC | own-law one-step program; not the old M/DQ model | 0.1165801595 | 0.1624694202 |
| J | full own-law Bellman program | 0.3692136149 | 0.3195140931 |

The two preregistered-in-the-local-protocol primary contrasts were E-C in IID
and OOD. Paired df=4 Student-t intervals use Bonferroni across those two
contrasts. Both lower bounds had to exceed 0.005; both failed:

- E-C iid: +0.0037535965; familywise interval [-0.0339288981, 0.0414360911].
- E-C ood: +0.0041999451; familywise interval [-0.0312064415, 0.0396063317].

E and G have identical confirmed policies. The spectral proposal retained
7-9 data-supported modes per action and chose zero edit for fit37. Its OOD
mean decreased; it does not qualify a new mechanism. EG is short optimization
of the same fixed head, with explicitly fresh stateless optimizer state, not
full-model training. J and MYOPIC change execution and receive no weight-edit
credit. All secondary comparisons remain descriptive.

## Identity, single-use confirmation and retained capabilities

The identity contract binds checkpoint/tensor bytes, network shapes and row
roles, protected model fields, generator and transition-table dependencies,
time/event/value units, code and the fixed external objective. Every accepted
candidate must preserve the encoder, Belief and core. The random control is one
signed permutation of the selected effective E delta and checks both norms
again after serialization.

The ledger reserves the complete 320-by-9 denominator, then persists STARTED
before each inference. A failed or lost attempt cannot be retried. Scores,
failures and partial states remain visible. The experiment records task utility,
OOD, policy-visit probability error, common-C-state preservation, cold policy
CPU, failures and nested construction costs. General retained capabilities,
independent data authority and live-market validity remain unqualified.

## Actual storage failure and transparent verification revision

The first verifier failed reopening the original WAL-backed ledger. The main
checkpoint's full integrity check passes and contains all 2,880 COMPLETE rows;
overlaying the retained valid WAL frames reproduces corruption. The original
main/WAL/SHM files and hashes are retained under `ledger_recovery_r1`. This is
an observed WAL/main inconsistency, not a proven SQLite-library or filesystem
root cause. Online close/reopen qualification **failed**.

`CHECKPOINT_SNAPSHOT.sqlite` is byte-identical to the original main database,
not reconstructed from score files. It reopens normally and all rows match
original scores. Offline recovery succeeds; it does not erase the online failure.

The second verifier detected a schema assumption: original TrainWorld reports
carry world_id, not schedule_sha256. The separate `verification_r3/verification.py`
retains the original frozen source map and replaces that nonexistent field
check with the complete frozen TRAIN-file hash, ordered world identities,
canonical known-history membership and mandatory complete 6,400-pair TRAIN
replay. No worker, raw record, candidate, threshold or numerical tolerance was
changed. Both failed verification attempts remain in the cost ledger.

The revision independently checks source/protocol/cohort identities, four-event
ordering, 2,896 historical and 320 new schedules, 45 model artifacts, 100 finite
path candidates, exact perturbation budgets, 2,880 durable receipts and all
fit-level statistics. It does not import the new candidate/worker/evaluator.
Eight behavior metrics and node counts replay independently; calibration field
normalization and aggregation are checked, without claiming a separately
implemented calibration evaluator.

## Costs and adoption

The complete worker used 206.044769 CPU seconds and 209.469557 wall seconds,
peak RSS 251,543,552 bytes. Successful full verification used 89.189256 CPU
seconds; the two failed verifier processes used 0.408256 CPU seconds. The sum
of these complete child processes is **295.642281 CPU seconds**. A separate
record preflight used 5.218702 internal CPU seconds; its startup/finalization
and other orchestration are unmetered.

Including the shared TRAIN preparation once in each alternative, candidate E
used 89.050833 CPU seconds versus G 91.535805: ratio 1.027905. Those inclusive
alternative figures must not be added together as physical work. They exclude
common final evaluation and publication and are not a complete-training speedup.
Cold finite-task policy CPU averaged 5.279ms for C and 140.100ms for J, including
J compilation. Different policy trajectory lengths also affect these numbers;
this is not a production throughput benchmark.

Agent tokens/service cost, energy, unknown previous trials and production
publication/recovery are null/unknown. No full NDU economic superiority follows.
The incumbent remains selected; new production weight adoption is false.

## Reproduction and review

Use the original frozen source checkout at `29a79d2`, the archived inputs and
saved output. Do not create new worlds or a new candidate search to replay this
experiment. Put the compatibility verifier under that source's
`tools/hcsn/wsp_confirmation_20261107/verification_r3/` and run:

```bash
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 python3 \
  tools/hcsn/wsp_confirmation_20261107/verification_r3/verification.py \
  --protocol /absolute/path/PROTOCOL_FROZEN.json \
  --run /absolute/path/execution_r1/run \
  --ledger /absolute/path/ledger_recovery_r1/CHECKPOINT_SNAPSHOT.sqlite \
  --output /absolute/path/new-VERIFIED.json --replay-train
```

The 13 preparation tests passed before confirmation. Original frozen tests and
source are retained. Any post-experiment ledger repair must be separately
qualified; it must not rewrite the original failure.

GitHub publication was rejected by automatic approval review. The pending
payload is a concrete local candidate for `TrillionniumFoundation/hepta-private-ci`,
branch `codex/wsp-confirmation-20261107`. No alternate host or credential was used
to bypass the rejection; the branch was absent in subsequent read-only remote
lookup. The patch and evidence remain available for explicit upload approval.
