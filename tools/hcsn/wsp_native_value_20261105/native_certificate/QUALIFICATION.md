# Qualification record

**Local software gates and the actual native MCP corpus passed.** The corpus
checked all five complete witnesses (21,458 rows), all 735 checkpoint-center
binary64 encodings, every returned exact rational quantity, both proof
branches, and all 21 declared controls. This qualifies the implemented verifier
for its stated mathematical scope. It is not a model-quality improvement.

The separate independent review and official GitHub CI must be assessed from
their own records. This document reports the retained local executions; it
does not turn a source publication or a code review into another execution.

## Fixed inputs and source

- Baseline: HeptaRuntime `990f85e46bedb8f49c0e6d0029ea6f9afbf6eac7`.
- Published source: draft PR #94,
  `bc38fb82244b946907886704b3c677bf00761cb9`.
- Existing `serde_json` `float_roundtrip` feature retained.
- Existing locked `num-bigint` 0.5.1 added as a direct pinned dependency. The
  actual lock comparison changes only the root package dependency list.
- Source recovery is a verified **partial checkout**: the baseline build inputs
  were checked against their exact Git blob IDs. There are 115 absent historical
  experiment artifacts outside the build inputs. No complete-checkout claim is
  made. Publication inherits the complete pinned parent tree.
- Old research sources, old run records and the old build cache were left
  untouched. Compilation uses a separate source directory and a copied cache.

## Observed executions

| Execution | Observation | Cost scope |
|---|---|---|
| `cargo fmt` and offline all-feature `cargo check` | PASS | 38.456 s wall, 45.923 child CPU s plus 0.122 driver CPU s. |
| All-feature `weight_*` library tests | PASS | 574.391 s wall, 1,035.486 child CPU s, maximum reported waited-process RSS 4,693,712 KiB. Includes compilation. |
| All-feature all-target Clippy with `-D warnings` | PASS | 60.133 s wall, 95.653 child CPU s. |
| No-default `weight_*` library tests | PASS | 627.160 s wall, 1,133.056 child CPU s. Includes compilation. |
| No-default all-target Clippy with `-D warnings` | PASS | 89.142 s wall, 145.318 child CPU s. |
| All-feature CLI build | PASS | 270.871 s wall, 494.319 child CPU s. |
| Final `cargo fmt --all -- --check` | PASS | 2.670 s wall, 2.634 child CPU s. |
| Five-fit fresh Python `Fraction` export | All 21,458 preserved witness rows; exact scalars/vectors equal the prior proofs | 13.771 s measured internal wall, 13.749 self CPU s, peak self RSS 82,876 KiB. This timer excludes interpreter startup/import and final manifest writing. |
| Actual native MCP, five fits plus 21 controls | PASS | Complete child plus waited descendants: 19.469 s wall, 6.6564 CPU s; supervisor adds 0.0295 self CPU s. Maximum reported waited-process RSS 426,764 KiB. |

Each feature configuration ran **87 passing tests, zero failures and two
pre-existing ignored tests**. All 12 newly added certificate tests ran and
passed in both configurations. The ignored cases are the owned-subprocess
`journal_crash_worker` entry and the prior NumPy actual-head ridge fixture test
that requires `HEPTA_WEIGHT_RIDGE_FIXTURE`. This selection did not run every
repository test. The complete software-gate process, including driver startup,
all seven commands and source/binary checks, used **1,630.793 s wall and
2,914.767 CPU s** for the child and waited descendants; the maximum reported
waited-process RSS was 4,693,712 KiB. This uses a copied pre-existing build cache,
so it is not a cold-build measurement. The initial check and setup above are
additional costs.

The compiled and executed binary is 382,495,848 bytes, SHA256
`692ea01fa5dd3a6e33cb343aee4d7c41a6ae4f015a352b2d2c42afd4655532ec`.
The execution protocol was frozen before native calls, SHA256
`7a361d5a451f9eba6b1d722e9596a4b30ba0b03fbf2aba057207c0a867b8dbd8`.
All native sources were unchanged both after qualification and at evidence
export. The binary was copied into the corpus directory, hashed before use,
and checked unchanged after the run.

| Fit | Complete witness rows | Native operation wall, s | RPC wall, s | Verdict and exact comparison |
|---|---:|---:|---:|---|
| 11 | 4,437 | 0.351809 | 0.684195 | F64 necessary system infeasible; all quantities and 147 center encodings equal |
| 23 | 4,427 | 0.375392 | 0.606835 | Same |
| 37 | 4,146 | 0.369092 | 0.575226 | Same |
| 53 | 3,776 | 0.351294 | 0.544235 | Same |
| 71 | 4,672 | 0.398303 | 0.624574 | Same |

The five native operation wall times sum to 1.845890 s; the five RPC wall times
sum to 3.035066 s. Neither number includes all corpus work. The whole-process
cost above also includes interpreter/driver startup, binary copy and identity
checks, MCP startup, input handling, controls and child shutdown. Driver-internal
self CPU was 4.0215 s; this is not native total CPU. A still-outer launch phase
including the supervisor process took 19.5698 s wall and 6.7536 CPU s. These are
nested scopes and must not be summed as independent costs.

The witness counts are 4,437; 4,427; 4,146; 3,776; and 4,672 for fits 11, 23, 37,
53 and 71. Inputs use complete nonzero witness rows, not producer-aggregated
vectors. The sum is 21,458. They reuse TRAIN data from the earlier study and
are not new independent holdout observations.

## Preserved setup failures and costs

The first controller request used a non-absolute executable and was rejected
before a process launched. An initial source-location read against the wrong
host returned a missing-path error; it did not mutate that host. The correct
source host was determined from an existing durable job's metadata.

The source clone's checkout reported missing Git objects on stderr despite an
exit code of zero. This was treated as an incomplete checkout. Every available
file was checked against the baseline tree; 22 missing build-input/source files
were recovered from byte-identical preserved files. Remaining historical
artifact gaps are explicit above. Setup, including the separate build-cache
copy, used 120.069 s wall, 28.923 child CPU s, and 0.007 self CPU s.

The first source overlay refused a mismatched baseline `Cargo.toml` checksum
before writing any file. The mismatch was one unintended final newline in the
locally retrieved baseline. The corrected overlay was accepted only after its
baseline bytes matched the Git blob. Both attempts are retained. The successful
overlay took 0.170 s wall and 0.011 self CPU s.

The complete input transfer uses 23 independently hashed parts, an independently
verified archive hash, and per-file hashes. The assembled archive is
11,939,840 bytes. Remote verification/assembly took 0.272 s wall and 0.224 self
CPU s; this is not the transfer's network elapsed time. Individual part receipts
and the transfer manifest retain their own costs. Control-plane/API latency and
unmeasured rejected-call host overhead are not reported as zero.

## Acceptance boundaries

All native exact quantities, both verdicts and all 735 parsed center encodings
matched the independent `Fraction` reference. The actual `tools/list` response
advertised the tool as read-only. The positive toy, equality, negative-sign,
zero and negative-zero, larger-budget and subnormal controls produced their
declared results. Negative/NaN/infinite multipliers; incorrect checkpoint,
witness or hidden hashes; wrong semantics, fit or hash-matching shape;
inconsistent teacher target; illegal competitor; repeated comparison;
conflicting source-row metadata; and unknown argument cases all rejected.
The subnormal control certified only the ideal-real system, preserving the
distinction from the F64 relaxation. There were no failed software or corpus
attempts; the earlier setup failures remain retained as described above.

Build/test CPU, input/export CPU, per-operation native wall time, transport RPC
wall time, and whole driver plus waited-native CPU are distinct scopes. The
whole-process supervisor includes interpreter startup, binary copy/identity
checks, MCP startup/transport, responses, controls and child shutdown. Its RSS
is the maximum process RSS reported by the OS, not summed concurrent memory.
Build and setup costs must not be omitted when discussing the cost of obtaining
this implementation. Timing one verifier is not a direct-edit-versus-training
quality or compute comparison.

The publication includes raw request/reference archives in `inputs/` and the
full execution records under `evidence/`. `evidence/BUNDLE_MANIFEST.json` binds
the 112 exported files, including all source/driver snapshots, command logs,
source manifests, protocol, raw MCP responses, whole-process receipts and
transfer records. `RUNTIME_SOURCE_MANIFEST.json` links the source bytes to the
separate runtime source publication. Original setup inputs/failure records
are retained under `provenance/`. The large copied executable and runtime state
database are not bundled; rebuilding the pinned source and repeating the
specified checks is the executable reproduction path.

No neural forward, training, model edit, witness search, held-out utility
evaluation, or production installation is performed by this native corpus. A
successful result qualifies a verifier for a fixed mathematical subsystem. It
does not qualify a weight repair or the broader AI optimization proposal.
