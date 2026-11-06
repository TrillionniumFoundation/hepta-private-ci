# HCSN PQ composition: exact-source acceptance and retained evidence

## Result and source identity

**The final source passed both dedicated hosted jobs.** [Run 42253531173](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/42253531173) completed successfully on `a20ea6a862e501d8a4993195c7da1ac52ca9a7be`, tree `b8e8b66b957aaf1e5e1cd9db8bb479137cf9fceb`.

[Source PR #5067](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/5067) contains the implementation. [Evidence PR #5088](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/5088) preserves this record, based on the exact source branch. The implementation is based on `44e539313e0c54badb4b9b687425dd87ecba6e67` and is split into 23 review commits. The first 22 are listed in [review-stages.json](review-stages.json); the final commit is the exact four-entry independent inventory repair described below.

**Dedicated HCSN acceptance is not an all-repository CI pass.** At the final blocking-gate observation, 2026-11-06 17:59:45 UTC, run `42253531351` was still pending with zero jobs. Its hosted no-bypass and cargo-deny gates had not executed on this final source. The new V8 workflow also has failed jobs, and the earlier cargo-deny failure remains unattributed. See [the blocking assessment](ci-final-blocking-assessment.json), [broader snapshot](ci-02-broader-snapshot.json) and [new V8 log assessment](ci-final-v8-assessment.json).

The machine-readable entry points are [acceptance.json](acceptance.json) and [ci-02-summary.json](ci-02-summary.json). Original run, jobs and artifact metadata are retained separately.

## What the final dedicated run establishes

| Scope on `a20ea6a` | Actual result | Boundary |
| --- | --- | --- |
| Strict Python | **69 passed, zero skips** | Pinned CPU runtime, float64; includes all five spatial compatibility tests |
| Neuron, artifact and contracts packages | **392 passed, one ignored helper** | The process helper is driven by the passing kill/reopen matrix; it is not counted as another passed direct test |
| Automation package | **120 passed, two ignored integration entrypoints** | Both entrypoints are invoked by exact-name wrappers across all three backends |
| Original signed bridges | **A, grid B and physical-time B all passed** | Two logical Cells have task-loss gradients; full state, weights and prediction replay exactly; the second block starts detached |
| Classical real cancellation | **Three backend executions passed** | Signed Start/Cancel, injected lost replies, original-worker termination, cold native owner recovery and zero mutating replay contacts |
| PQ Agentd real cancellation | **Three backend executions passed** | The same ignored acceptance entrypoint runs once per backend; actual local ML-DSA trust fixtures, original-worker termination and cold recovery |
| Selected Agentd regressions | **23 passed, 169 filtered or ignored** | This is not the complete Agentd test suite |
| Ordinary non-test Agentd library check | **Passed** | Normal Linux registration code compiles; the daemon and AuthBus ingress were not booted by this fixture |
| Scoped Clippy and source-unchanged checks | **Passed in both jobs** | Original warnings are retained; no zero-warning claim |

Overlapping suites and ignored/filtered tests are not added into an aggregate pass count. The source job was `128014547080`; the Agentd job was `128014547600`.

The [source audit](ci-source-42253531173/artifact-review.json) checks the new run's three bridges, three classical cancellations and 139 Git source hashes. The [PQ audit](ci-agentd-42253531173/pq-host-audit.json) checks all 11 protected source pins, the complete 54-file Python inventory, 159 retained-file digests, raw terminal-to-observation-to-cold-receipt linkage, persisted nonce frames, independently recomputed frontier state and SQLite history. These offline checks read the actual new artifacts; they do not independently rerun numerical computation, signatures or the CI host's live `/proc` observations.

The native executable digest happens to match the first round. New process identities, terminals, receipts, databases and retained-file manifests were nevertheless audited from this new run. Equal executable digests were not used to infer that new execution occurred.

## Numerical and cancellation semantics

Physical-time B admits positive integer microsecond intervals under its profile, event and resource budgets. Spatial discretization, frozen within-step coefficients and right-endpoint deposition remain numerical approximations. The separate trusted authority clock governs authorization validity; it is not a replacement for the numerical time profile.

Full numerical state crosses the persistence boundary. The subsequent training block starts from a detached restored initial state; no autograd graph is claimed to survive serialization. BP uses gradients of the real task loss in the shared tensor graph. NDU, credit receipts, eligibility, value scores and local plasticity retain separate meanings and do not substitute for parameter gradients.

The cancellation requests retain the original ceilings: 64 optimizer steps, 1,048,576 working elements and 24 KiB of host wire data. Both population cancellation fixtures explicitly use 8 spatial bins and longer admitted traces. The ordinary default remains 32 bins, with canonical graph/checkpoint encoding preserved and tested. The cancellation fixture is not a new numerical-quality benchmark.

Each cancellation proves that the original live worker incarnation stopped, with `cancelled_worker_stopped` recorded and the cancelled job's candidate, handoff and failed-output files absent. The initial indeterminate history remains preserved. Cold recovery yields Start `failed` and Cancel `succeeded`. Classical cases inject lost Start and Cancel replies; PQ cases retain the actual initial replies and inject no lost responses.

**Optimizer entry in the cancelled worker remains unproven.** The one-step admission preflight is a separate execution, and no completed 64-step timing or energy measurement is inferred from it.

## Independent no-bypass repair and broader CI

The first source, `bbe995c43e4eed4bb9c217b52447ba5a32ebb6ca`, passed [dedicated run 42240138316](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/42240138316). Its broader repository check then exposed a real omission introduced by this port: three new helper methods and the signed PQ revocation wrapper were absent from a separate independent authority inventory. The existing caller verifier itself passed, but two of the 17 independent B4 tests failed.

The final source changes only `qa/b4-no-bypass/KERNEL_AUTHORITY_BOUNDARIES.json` relative to that first source:

- Classify `authentication_profile`, `shares_owner` and `check_unclaimed_grant` as non-authorizing methods. They issue no token, consume no nonce and invoke no provider. The readiness check may read a clock and does not replace a real claim or final-entry authorization.
- Add only the exact `codex-rs/hepta-contracts/src/final_use_control_pq.rs` signed wrapper path to the existing revocation boundary caller list.

Every prior classification/caller, the schema, checker, tests, `CALLERS.toml` and runtime implementation remain unchanged. The original **17/17 tests passed locally** on the exact inventory bytes later committed as `a20ea6a`, followed by repository `just fmt`; no local tests ran after formatting. The inventory SHA-256 is `0402f9abcc8ea35f6541e1673611bae09da4bb85e5ba25c827d4efc12ee77500`.

The [original failure and repair archive](ci-01-controls-raw.tgz), [independent review](ci-01-independent-inventory-review.json), [final gate assessment](ci-final-blocking-assessment.json) and [final raw gate observations](ci-final-blocking-raw.tgz) preserve the distinction between local success and a hosted gate that had not started. Dedicated HCSN acceptance does not replace the full-repository blocking gates.

The earlier cargo-deny job `127995822924` failed its actual `Run cargo-deny` step. Its decoded log could not be fetched, and the normal browser view required sign-in. The [static assessment](ci-01-cargo-deny-assessment.json) retains identical baseline/current workflow and policy inputs and finds no new explicitly banned package source/name or dependency edge. It does not establish license/advisory results or the actual failure cause. This failure remains **unknown**, with no blanket baseline or infrastructure attribution. Exact inputs and attempts remain in [the cargo-deny archive](ci-01-cargo-deny-raw.tgz).

Other broader failures are recorded individually. First-round Windows checkout path-length errors and V8 DNS/compiler-artifact version errors remain preserved. New final-source V8 failures are assessed from their own logs in [ci-final-v8-assessment.json](ci-final-v8-assessment.json), rather than inferred from the earlier run. The separate ARM source-head commands passed on the first source; that earlier ARM result is not relabeled as final-source execution.

## Raw artifact retention

| Package | Retention |
| --- | --- |
| [Final source filtered ZIP](ci-source-42253531173/source-raw-filtered.zip) | 669 of 672 original members, byte-identical. Exactly three confirmed compiled ELF bridge executables are excluded from Git. |
| [Source original-member inventory](ci-source-42253531173/original-artifact-files.json) and [provenance](ci-source-42253531173/source-raw-provenance.json) | Every original member's identity, all three excluded paths/sizes/SHA-256 values, matching native-build receipts and official original ZIP digest. The filtered package is not the complete original artifact. |
| [Final Agentd original ZIP](ci-agentd-42253531173/agentd-complete.zip) | All 185 original members, with the exact official ZIP digest. No compiled native executable is present. |
| [Final Agentd filtered ZIP](ci-agentd-42253531173/pq-host-raw-filtered.zip) | The same 185 original members, independently read back and verified; zero exclusions. |
| [Agentd job archive](ci-agentd-42253531173/job-evidence-raw.tgz) | Full decoded job log, steps, provenance and original decoded connector response. |
| Offline audit tools | Exact helper bytes are in per-job `offline-audit-tools.tgz` archives with member hashes, so no new loose Python source is introduced into the signed inventory. |
| [Local development archive](local-raw.tgz) | 489 regular files, totaling 8,373,205 uncompressed bytes. One Unix socket is represented by path/mode metadata only. |

The final source original ZIP SHA-256 is `9fa1a9212ca2a2a5d395b2b020d8f48445bfbe13d950ce12fc6fe953da6e5d51`; its filtered package SHA-256 is `cd2595435359490555779f832eaf203c18dd0e71bbdd8d933050fac2de0e2ba7`.

The final Agentd original ZIP SHA-256 is `9f339af4602f67ee578dd45e6be0619fa55557d5cf6acf0c62b6f1c4d4441c7e`; its repackaged ZIP SHA-256 is `7ab4adce82adda78cc8b64754f827444b45dce64178fa4c3b2d39354d1c6d119`.

Original GitHub artifact IDs are `13526821341` and `13526813253`; their advertised expiry is 2027-02-04T16:33:44Z. Durable Git packages preserve the described contents independently of that expiry. Complete source ZIP/extraction remain in scratch, including the three native executable bytes; those executable bytes are deliberately not committed to Git. The Agentd complete ZIP is committed because it has no compiled executable exclusions.

## Earlier observations stay intact

[local-validation.json](local-validation.json) retains 40 observations and 132 distinct referenced files. It preserves the local 192-pass/5-EPERM contracts result, 120-pass/2-ignored Automation result, the earlier 64-test Python pass, four completed spatial tests followed by two exit-137 starts with empty logs, failed early cancellation attempts and later one-step preflights. The first hosted candidate and final hosted candidate are recorded separately. Unknown historical source snapshots remain unknown, and prior failures are not overwritten by later success.

The original closed-caller audit retains 51 boundaries, 25 protected entries covering 24 unique paths, 11 exact source pins, 4,452 scanned Rust files, 14 undeclared-caller negative probes, ten typed checker tests and its self-test. All 45 baseline boundary IDs and existing caller entries are preserved. Two verification-marker lists (`final_use_claim_raw` and `final_use_approval_verify`) were adapted to the PQ validation paths, and the revocation boundary adds the exact authenticated `final_use_control_pq.rs` caller. The checker code is byte-identical to the baseline. The exact Git-object comparison in `ci-02-summary.json` corrects the earlier overbroad wording that all baseline definitions/caller sets were unchanged; prior raw records remain intact. Real Cargo/Bazel dependency lock regeneration and scoped fix/format records remain in the local development archive.

## Production boundary

This work implements normal Linux schema-3 registration for `hcsn_process_v1` with `production_ml_dsa65_v2` and exercises the actual host path under locally signed trust fixtures. Signed deployment, source inventory, protected descriptor reads, external clock/frontier observations, durable claim binding and final native contact checks are covered by the retained regressions and real worker cases.

The fixture does **not** establish a deployed production service, independently controlled production keys, a booted Agentd daemon or AuthBus ingress. AuthBus remains Ed25519. The signed source snapshot and contact checks do not establish atomic source-directory or runtime custody; that remains an operator deployment requirement. No model adoption, NDU/scientific improvement or physical-energy benefit is asserted. The desktop CUDA campaign was untouched.
