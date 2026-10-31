# V13 memory-cell persistence and migration qualification

## Result after two three-VM runs

**Strict cross-VM continuation passed in run 41206138368 under the recorded
baseline numerical profile.** Three GitHub-hosted jobs with distinct boot IDs
transferred the actual adapter checkpoint, restored the pinned backend on the
destination, and continued training. All thirteen original strict checks passed.
An independent read-only audit of the downloaded NPZ files confirmed identical
raw bytes for every parameter, Adam moment, sampler array and metadata field at
both 90 and 97 updates. The second runner used a different AMD EPYC CPU model
from the first and third runners.

The first run, 41205095256, **failed** the exact-state gate at float64 rounding
scale and is retained in full. The only source change before the second run was
an additional numerical profile helper and workflow settings that disable NumPy
CPU dispatch above the wheel baseline. The seven original scientific source and
dependency files, exact-state gate, inputs and thresholds remained unchanged.
The first run did not record effective ufunc dispatch, so its specific cause is
not proven by this successful repair experiment.

The earlier three-process local continuation also passed; that is local process
recovery, not a VM claim. The successful CI result is limited to the exact frozen
input, adapter implementation and recorded runtime profile. These runs do not
demonstrate a network economic advantage or a general-purpose memory system.

Primary records:

- [Successful second run 41206138368](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/41206138368), attempt 1, 2026-10-31 UTC: [qualification JSON](evidence/migration-ci/run-41206138368/QUALIFICATION.json), [original verifier](evidence/migration-ci/run-41206138368/expanded/13043549087/VERIFY.json), [independent array comparison](evidence/migration-ci/run-41206138368/INDEPENDENT_ARRAY_COMPARISON.json).
- [Failed first run 41205095256](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/41205095256), attempt 1: [qualification JSON](evidence/migration-ci/run-41205095256/QUALIFICATION.json), [original verifier](evidence/migration-ci/run-41205095256/expanded/13044053203/VERIFY.json), [independent array comparison](evidence/migration-ci/run-41205095256/INDEPENDENT_ARRAY_COMPARISON.json).
- [Local run and commands](evidence/migration-local/RUN.json), [local positive verifier](evidence/migration-local/verify/VERIFY.json), [local Adam corruption verifier](evidence/migration-local/negative-adam/verify/VERIFY.json).
- Archive/member hashes and full evidence inventories: [first downloads](evidence/migration-ci/run-41205095256/DOWNLOAD_FINAL.json), [first inventory](evidence/migration-ci/run-41205095256/INVENTORY.json), [second downloads](evidence/migration-ci/run-41206138368/DOWNLOAD_FINAL.json), [second inventory](evidence/migration-ci/run-41206138368/INVENTORY.json).

## Frozen inputs and executable identity

The first run checked out commit `f3069e82ebd98b3d22c33bee32096f5217783e79`, tree
`84ba9f6e3089e5e17a00fe83a3e6173aff54d12f`. The tree equals local commit
`569859fdadd70c2ebbb318515f6902cfba0fa4d2`; the separately recorded
[publication mapping](evidence/publication/INITIAL_MAPPING.json) explains the
different commit identities. The second run checked out its direct child
`8ae2d91947203a868f880312df823004b7289f25`, tree
`b1b399ae4819bb6c4cee9fe720fe4227bd12bfa1`. The [raw commit record](evidence/migration-ci/run-41206138368/GITHUB_COMMIT.json)
confirms that only the workflow and new `numerics_profile.py` changed. All six
training-node receipts across both runs have identical hashes for the seven
original executable/dependency files bound by the migration contract. No frozen
scientific source or acceptance threshold was changed.

The inputs are 120 actual training texts encoded by the fixed pretrained
MiniLM backend into a 120-by-384 float32 matrix. They are not generated substitute
features. The adapter has 10,764 learned float64 parameters and full Adam first
and second moments. This qualifies the residual adapter and classifier head on
a frozen encoder; it does not train or migrate a trainable encoder.

| Identity | SHA-256 |
|---|---|
| Frozen feature NPZ | `69ec1a8c3d7eda6f9602a3bfddfbcaa7f0cfe4cabe40c90d2ef524998afe02ab` |
| Canonical training-source version | `19ebe0c1c2686688df7327baf7334165b18d5d95c8fac4f3ce013809a8ae328f` |
| Encoder identity | `8b8d070f392fd30181f217daa4de166dfe785897b5d4d64f2244bc6fcb5f42aa` |
| Input manifest file | `504c25fe0ff8202a1409a885ce46f7e3df6082141081c348963084f8aefdf978` |

Preparation trains a 35-step prefix and an independently uninterrupted 90-step
reference from identical initialization. It also saves the reference after seven
more updates. Resume restores weights, Adam moments and step, RNG, shuffle order,
cursor, source identity, and encoder identity, then performs 55 updates. Verify
compares the 90-step states, performs another seven updates on the third VM, and
compares to the independently prepared 97-step reference. Comparisons use the
whole causal-state hash; prediction equality alone cannot pass the gate.

## Persistence and local process recovery

The CI preparation job passed all four lifecycle tests. These cover a single
SQLite source owner, immutable revision cuts, scope and encoder validation,
stale dependency rejection after correction/retraction, and actual child
`SIGKILL` before and after the publication transaction. Old artifacts and history
remain retained. The tests establish invalidation and publication behavior,
not machine unlearning or deletion of historical parameter influence. Their
controlled source examples are synthetic; they are separate from semantic task
evaluation. The complete test output is retained in
[lifecycle-tests.log](evidence/migration-ci/run-41205095256/expanded/13043793658/lifecycle-tests.log).

The real-input local migration used three independent processes on one host.
All ten positive checks passed, including exact 90-step and 97-step complete
states. A separate negative verifier invocation modified one saved Adam first
moment (`m_A[0,0] += 0.125`) and updated the outer checkpoint-file receipt. Current
predictions stayed unchanged; complete state and subsequent training differed,
so the verifier rejected it. This prevents a successful prediction probe from
concealing missing or corrupted training state. The copied negative fixture is
not another resume execution; the four actual commands and process durations
are listed in `evidence/migration-local/RUN.json`.

## First CI run: strict failure retained

| Role | GitHub job ID | Boot ID | Result | Job wall time |
|---|---:|---|---|---:|
| Prepare | 124548448867 | `05c30e2b-47d4-4822-ba6a-b777c3ca72d2` | Success | 15 s |
| Resume | 124548517769 | `a0471a76-c943-44da-87ef-357509cd63c1` | Success | 28 s |
| Verify | 124548636031 | `79acd265-dde3-474b-819a-efcff74ba401` | Failure at exact-state gate | 15 s |

The three jobs used distinct boot IDs despite identical image-derived hostnames.
Run ID, attempt, commit, seven file hashes, Python 3.12.3, NumPy 2.3.5, single
thread settings, and `OPENBLAS_CORETYPE=NEHALEM` agree. The receipts do not record
CPU model, NumPy ufunc dispatch, or a complete numerical runtime profile.

| Check | Attempt 1 |
|---|---|
| Current full causal state equals uninterrupted reference | **Fail** |
| Full state after seven additional updates equals reference | **Fail** |
| Current class predictions and predictions after seven updates | Pass |
| Sender's state and predictions equal the received checkpoint | Pass |
| Expected update count | Pass |
| Wrong encoder, source version, and feature identity rejected | Pass |
| Three distinct boots and three genuine CI jobs | Pass |
| Destination reconstructs and probes the fixed encoder | Pass |

An independent read-only NPZ comparison found identical metadata bytes and
sampler order. At step 90, 8,870 of 10,764 parameter values differ, with maximum
absolute difference `3.3306690738754696e-16`. Maximum Adam first-moment and
second-moment differences are `1.1058862159352145e-17` and
`1.0842021724855044e-19`. At step 97 the largest parameter difference is
`3.7470027081099033e-16`. The [comparison JSON](evidence/migration-ci/run-41205095256/INDEPENDENT_ARRAY_COMPARISON.json)
records per-array shapes, element and bitwise difference counts, byte equality,
and maximum absolute differences.

These observations are consistent with different floating-point execution
paths. They do not establish a specific CPU or library cause from this run.
Fixing the BLAS core does not itself document the rest of the numerical profile.
The second execution-profile qualification below retains this failure, records
the effective numerical runtime on every node, and keeps the exact gate. The
producer's `cross_vm_claim: true` describes the exercised topology; overall
acceptance additionally requires `passed: true`, which the first run does not have.

## Second CI run: exact continuation accepted under a checked profile

| Role | GitHub job ID | Boot ID | CPU model | Result / job wall |
|---|---:|---|---|---|
| Prepare | 124551477821 | `7ae41f16-70c9-48e3-92dc-22b1e00aa5c6` | AMD EPYC 9V74 | Success / 12 s |
| Resume | 124551577260 | `c49f95d4-a4ad-4671-bf20-3d73b67297d5` | AMD EPYC 7763 | Success / 39 s |
| Verify | 124551738613 | `07e7e471-ef75-49da-833e-09ba0ab94f9f` | AMD EPYC 9V74 | Success / 17 s |

The workflow retains the existing `NEHALEM` BLAS core and one-thread settings,
and disables all 17 compiled NumPy dispatch feature entries above the baseline.
Each VM independently captures the profile after dependency installation and
before training. The verifier compares the three profiles before executing the
original migration verification. These are actual independent captures, not the
explicitly marked local role-copy fixtures used to check the helper itself.

All three profiles record `enabled_dispatch=[]`. For float64 `tanh`, `exp`,
`sqrt`, `add`, `subtract`, `multiply`, and `divide`, the actual selected kernel is
`baseline(SSE SSE2 SSE3)`. Comparable profile SHA-256 is
`82afc78979e4617c3ac9d0afcb06b845c35ddb3b6b5e98243c28b67e32f77f5a`
on all three VMs. The comparison also requires matching NumPy core and bundled
OpenBLAS file bytes/SHA-256, Python/libc, effective flags, environment values,
helper SHA, and run/source identity. Raw CPU capabilities, hostname, and absolute
paths are retained separately and are excluded from equality.

The [original profile comparison](evidence/migration-ci/run-41206138368/expanded/13043549087/NUMERICS_COMPARISON.json)
passed with no differing fields. Independent audit verified each profile file's
hash, canonical comparable hash, correspondence to its actual training-node boot
ID and job, and binding to this run/attempt/head. Every original strict migration
check passed. The independently audited 90-step and 97-step NPZ arrays have zero
unequal elements and identical raw bytes, including metadata. At step 90 both
full-state hashes are
`372c31bdc7e4197752fbc08ed2d61253ea6fa642de01cb6748d791de1d7504e2`.

This is one successful qualification under an explicit runtime profile following
one retained failed qualification. It is not a guarantee for arbitrary numerical
libraries, hardware, datasets, longer training histories, or unsupervised network
evolution.

## Destination backend reconstruction

In each run, resume downloaded the eight official files for
`sentence-transformers/all-MiniLM-L6-v2` at revision
`1110a243fdf4706b3f48f1d95db1a4f5529b4d41`. The expected source identities, each
file's SHA-256 and size, package versions, and complete encoder manifest matched.
It then re-encoded all 120 canonical training texts and probed the resumed
adapter. Both original runtime-restore receipts contain full file identities and
predictions: [first](evidence/migration-ci/run-41205095256/expanded/13043557680/runtime-restore.json)
and [second](evidence/migration-ci/run-41206138368/expanded/13044581106/runtime-restore.json).

In both runs, the maximum embedding difference from the frozen inputs was
`8.940696716308594e-8`, within the explicitly declared encoder replay tolerance
`rtol=1e-6, atol=1e-7`. All class predictions agreed. The adapter's checkpoint
file SHA and full causal-state hash were unchanged by inference. This embedding
tolerance does not relax the separate exact adapter-state requirement.

## Measured costs and limits of interpretation

| Measurement | First run (failed) | Second run (passed) | Scope |
|---|---:|---:|---|
| Prefix checkpoint | 249,934 B | 249,942 B | Full adapter/Adam/RNG/sampler NPZ |
| Handoff ZIP | 423,988 B | 426,193 B | Actual features, checkpoint, manifest, receipts; second includes profile |
| Resume artifact transfer clock | 1.055916 s | 2.202387 s | Download/extraction and action/service overhead |
| Resume checkpoint load | 0.009486 s | 0.009404 s | Internal process measurement |
| Resume 55 training updates | 0.017575 s | 0.018606 s | Internal process measurement |
| Resume checkpoint save | 0.009640 s | 0.009499 s | Internal process measurement |
| Verify artifact transfer clock | 2.547401 s | 3.117515 s | Second also includes profile comparison before migration entry |
| Cold encoder payload | 90,873,127 B | 90,873,127 B | Official model/tokenizer/config files |
| Cold encoder download | 2.166818 s | 3.674572 s | Excludes package installation |
| Encoder initialization | 0.363409 s | 0.358131 s | CPU ONNX backend |
| Encode 120 source texts | 0.594233 s | 0.587023 s | No held-out quality test |
| Adapter inference probe | 0.000848 s | 0.000845 s | Re-encoded and frozen features |
| Complete runtime restoration call | 3.142793 s | 4.637609 s | Excludes interpreter/import and pip |
| Runtime restoration peak RSS | 216,624 KiB | 216,368 KiB | Process peak, not incremental cell RAM |
| Dependency installation steps | 4 / 17 / 6 s | 5 / 20 / 6 s | Prepare / resume / verify; one-second API resolution |
| Sum of three job wall times | 58 s | 68 s | Not billed minutes or CPU time |
| Run start to last job completion | 68 s | 89 s | Includes scheduling gaps |

| Known payload category | First run | Second run |
|---|---:|---:|
| All five artifact uploads | 2,358,528 B | 2,369,687 B |
| In-CI artifact downloads | 1,603,621 B | 1,610,150 B |
| Cold encoder download | 90,873,127 B | 90,873,127 B |
| **Known CI payload lower bound** | **94,835,276 B** | **94,852,964 B** |
| Later audit ZIP downloads outside CI | 2,358,528 B | 2,369,687 B |

In-CI artifact downloads comprise handoff twice, reference, and resumed
artifacts. These figures are lower bounds on payload, not measured network wire
traffic. Package wheels, checkout, action downloads, log transfer, HTTP/TLS
overhead and any retries are additional. The prepare-evidence upload deliberately
duplicates handoff and reference files; it is counted as traffic, not another
training experiment. The two runs are separate executions and are not pooled
into a latency or cost estimate.

Fine-grained upload content/finalization timestamps and all job/step times are
retained in each run's `QUALIFICATION.json` and three complete original job logs
under its `logs/` directory. Each run's five original ZIP files are retained under
`zips/`; their byte lengths and SHA-256 values match GitHub's advertised metadata.
No signed audit download URLs are stored.

These measurements show real transfer and cold runtime reconstruction costs.
They do not establish amortized savings, favorable total network cost, monetary
billing, distributed ownership correctness, open-ended cell evolution, or a
general memory system. The small local adapter update time should not be
presented as the end-to-end migration cost.
