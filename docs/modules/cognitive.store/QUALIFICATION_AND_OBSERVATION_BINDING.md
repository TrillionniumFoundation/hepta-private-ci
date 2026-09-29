# Committed qualification and final-use publication observation

This change continues PR #1038 from `a7d89cb71229b8ef8773c5b11e97b1e6c8ce5aed`.
The existing SQLite owner, semantic/provenance transaction, production host,
normal read pages, release recovery profiles, archive codec and native owner
oracle are unchanged. No active database, source, backup or archive is erased.

## Qualification must execute the committed plan

Previously, the manifest checked Git/run identity and log digests but did not
compare each recorded command or test threshold with the committed plan. A
successful weaker command could therefore occupy a required record name. The
shared command wrapper retained its minimum after execution, but did not bind
the selected plan specification or timeout in the execution record.

`cognitive_store_plan.py` now supplies one strict interpretation to the runner
and manifest. It validates the complete plan before any dispatch, including
unique safe record names, bounded arguments, existing non-redirected working
directories, integer test minima and deadlines, and workload-only environment
assignments. Workload configuration cannot replace source/base/run identity or
the command-specification binding. Unknown fields, duplicate JSON keys, path
escapes and unresolved variables are rejected. The canonical plan must be the
unchanged Git object in the tested candidate, not a supplied subset in `/tmp`.

Every command specification binds the record name, fully expanded argument
vector, working directory, workload environment, native-preparation requirement,
minimum test count and timeout. `hepta_ci_exec.py` retains its actual minimum,
timeout and the runner's specification digest; its execution behavior is
unchanged. This additive change is exercised by all three existing shared-runner
regression suites.

The manifest independently resolves the committed specification and compares
these fields. It opens bounded regular single-link records/logs without following
symlinks or blocking on FIFOs, checks retained identity and digests, and derives
test counts again from the raw runner summaries. A claimed test count cannot
override the log. Independent commands cannot share one log. Missing native
preparation remains `not_executed`; missing plan binding, weaker commands,
changed workload, missing thresholds or altered evidence cannot be a pass.
Failure dossiers remain diagnostics, not qualification or deployment authority.

This binds the reviewed runner and plan; it is not attestation against a
compromised runner capable of forging every input. Independent runner identity,
review and artifact custody remain necessary. Both exact source-head and
ordered-parent deterministic base-merge lanes still require their own results.

## Observation uses the existing descriptor owner

The normal `archive.py --reconcile-plan` path now pins the authorized scratch
directory before reauthorization. It uses `archive_publication.PinnedDirectory`
for private staging rather than creating and recursively cleaning a pathname
resolved after a callback. Decode/copy writes are directory-relative.

After the native checker, observation retains the created image descriptor,
checks its inode against both the creation record and current directory entry,
and rehashes the complete bounded payload. Final reauthorization occurs while
that descriptor is retained. Directory identity, private single-link file
identity and payload are checked again before a success report. Clock regression
and expiry during final payload reading are rejected. These checks also cover missing-output observations where applicable.

Cleanup removes only the scratch image created by that operation. Replacement
inodes, extra links and unknown children remain for governed inspection; they
are not recursively erased. The report is an observation, not an atomic
transaction across all external owners, a proof of a prior successful fsync,
permission to replay, or admission of a live writer. Original outputs are neither
rewritten nor adopted. Host OS-principal and mount isolation are still required.

## Executed local regressions

| Suite | Cases | Scope |
|---|---:|---|
| `test_cognitive_plan_binding.py` | 39 | Strict plan parsing; actual runner and manifest in disposable Git repositories, including a two-parent merge |
| `test_cognitive_qualification_manifest.py` | 11 | Existing manifest identity, failure and raw-evidence regressions |
| `test_hepta_ci_exec.py` | 15 | Existing shared runner and shell command-binding regressions |
| `test_hepta_ci_exec_deadline.py` | 9 | Existing deadline, process and bounded-output regressions |
| `test_hepta_ci_exec_output.py` | 21 | All cases passed in three disjoint seven-case batches after full-run authoring attempts exceeded the local execution window |
| `test_publication_observation.py` | 35 | Existing signature, codec, filesystem and publication-observation cases |
| `test_observation_boundary.py` | 17 | Final-use image/directory identity, changed bytes, links, retained unknown evidence and failure cleanup |

The 147 distinct cases above passed on the authored Python changes. Archive
protocol tests use actual cryptography/filesystem operations but explicitly mock
the native owner checker; these are not Rust or target-host results. The shared
runner's miniature commands are fixtures, not cognitive product qualification.
Three manifest counterexamples and four observation counterexamples fail their
regression assertions with the original implementation and pass with the change.
The original manifest and observer blobs are respectively
`b33ef40992ac949b9006d0cfab5d529bfbad40a6` and
`462f95c0629c56243e1360cedaeefd0719155a3e`.

The committed qualification plan retains every one of the prior 42 commands
and adds five independent records: plan-binding tests, three shared-runner suites
and observation-boundary tests. All 47 commands remain required in each lane.
The implementation map and generated status/dossier bind the new sources; local
regression counts never set product, host, acceptance or release flags.

## Remaining delivery gates

Current-candidate native build/test/strict lint, real owner crash/recovery and
release measurements still need terminal execution. No local Rust toolchain was
available. Independent signed-host bootstrap, current-cut publication-gap
reconciliation, filesystem faults, restart, rollback and SLO acceptance remain
separate. Destructive ancestry-safe hot pruning and actual per-owner physical
erasure/unlearning are not implemented by this change. Cold archives and signed
owner assertions cannot substitute for those operations or their acceptance.
## Committed-plan identity in terminal manifests

Qualification manifest v3 binds two stable layers in addition to the resolved command-spec digest. `qualificationPlanSha256` is the canonical digest of the complete committed plan object, and each command row carries `planEntrySha256`, the canonical digest of its unexpanded plan entry. The source-head and deterministic base-merge lanes may resolve different candidate and scratch paths, but neither can substitute a command, workload, limit, working directory, native-preparation disposition or evidence inventory without changing one of these committed identities. Independent acceptance recomputes both layers from the bundled canonical plan.
