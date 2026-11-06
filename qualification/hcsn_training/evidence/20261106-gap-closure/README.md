# HCSN gap-closure source and evidence

Implementation entry point: [PR #5001](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/5001). All nine review stages are draft and below 500 changed lines each. Final source is `44e539313e0c54badb4b9b687425dd87ecba6e67`, tree `b7ac591c98b6045521f70e97f58dc2cea8bf12bc`.

## Final exact-source qualification

Both jobs of [HCSN run 42222767973](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/42222767973), attempt 1, completed successfully for the final source:

| Gate | Result |
| --- | --- |
| Python numerical, derivative and supervisor suite | 56 passed, zero skips |
| Native affected-package suite | 195 passed; one child-process helper skipped from standalone discovery |
| Automation suite | 119 passed; signed fixture is explicitly executed below |
| Signed real-worker fixtures | A, fixed-grid B and physical-time B each passed |
| Owner/cold replay and second blocks | All three backends passed; complete state, weights and predictions exact; two optimizer steps in each second block |
| Selected actual Agentd tests | 7 passed; 168 filtered tests not executed |
| Agentd Clippy and unchanged tracked source | Passed |
| Original privileged caller closed set | Passed in dedicated Agentd and general repo-checks jobs |

`ci-44e5393/` retains the final qualification bundle and an independently checked summary. Its main artifact is Actions artifact `13505170495` (7,052,020 bytes; SHA256 `a27f8aeaed93c0afe97addbeb84df83d125e43493fb0200e938f6fefcbd27614`). Its Agentd artifact is `13504634465` (30,445 bytes; SHA256 `a34f9ec9fdf7781fff3ec4f5e55fc6df93b63214a7e43527bde1299ed0f6c776`). Both original ZIP digests were verified from downloaded bytes.

The actual Agentd artifact includes `callers.json`: `PASS_HEPTA_CALLER_CLOSED_SET`, 4,421 Rust files and 45 boundaries, with `authorityGranted=false`. Authority construction stays in a private method of the existing Agentd effect owner; neither the allowlist nor verifier changed.

The [general repo-checks job](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/42222768205/job/127911561653) also passed all its steps, including the unchanged caller proof, formatting, Prettier and clean-worktree checks. Its actual checkout `c103778518b2f8bb1dbee6db78021150b633e35e` has exactly the final candidate tree. This individual job result does not make the whole-repository workflow green.

## Retention and provenance

The main artifact has 530 regular ZIP members. The retained bridge bundle preserves all 527 non-ELF members; the three executable members are identified by digest and size in the manifest. The signed-worker executable is identified by its recorded SHA, with the missing byte count explicitly recorded. Required checkpoints, handoffs, owner/SQLite state, source identities, Cargo records and complete logs are retained.

Actions reported one unsupported entry during the original upload. The 531-to-530 count, negative-test source and generated directory are consistent with the deliberate FIFO fixture. The uploader did not name the path and remote lstat was unavailable; this attribution is not a claim of retaining the entire source filesystem.

The executor was replaced after qualification. Current CI evidence was restored from the identical remote artifacts and cloud-retained complete logs; rebuilt review/package hashes are recorded separately. This recovery did not rerun tests or modify the source. The reconstructed final source manifest is labelled as reconstructed and does not pretend to be the lost local manifest bytes. Exact source identity remains the published Git commit and the CI source records.

`FINAL_SOURCE.json` records the current candidate and stage identities. `final-preparation.json` is historical preparation evidence for the first candidate `e62f132`; it is not relabelled as final-head preparation.

## Earlier candidate and physical execution

`ci-e62f132/` retains dedicated [run 42220007503](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/42220007503) for exact first candidate `e62f1329142c5752d0344b5fa64f3a9c981f4be5`, including its successful HCSN gates and original broader caller/readiness failure logs. The broader proof found the introduced out-of-owner authority constructor; the final candidate corrects it and was qualified independently.

`ai395/` keeps unchanged subtree `42d568588a7572d4d364a344912ed59492a84487` from `7176667c0807ee49bd6bfc9a571b175f44a243a1`. It contains three real CPU acceptances, binary build/strip linkage, retained local logs and explicit accounting for the first interruption's lost RAM-only bridge trees. Original source was recovered byte-for-byte at `e989d51b0da0617aa20a1fccbcbcb4ad01571ff4` before formatting.

Physical helper results state `host_registration_exercised=false`. Actual Agentd tests have their separate CI job. The second blocks use new real workers and owner recovery; they are not second signed TaskFlow dispatch tests.

## Scope and unresolved production work

Actual task-loss autograd is separate from NDU, credit, eligibility and local plasticity. Physical-time B uses a conservative discrete CTMC and positive integer-microsecond refractory cohorts within admitted time/event/resource budgets. Finite spatial grid, frozen coefficients and right-boundary deposition remain explicit approximations. Complete numerical state crosses persistence; each new block starts detached.

Engineering registration is test-only. Ordinary debug/release builds and the uncomposed `production_ml_dsa65_v2` profile are refused. Real PQ authority/trust/ingress composition and deployment remain on hold. No production adoption, scientific gain or energy measurement is claimed. The existing CUDA campaign was not contacted.

The broader repository workflow is not green. Known baseline files are unchanged: README readiness discovery, Windows long evidence paths, an old plasticity test's removed `append_qualification` call and existing Bazel lint issues. Cargo-deny also failed and its cause is not claimed diagnosed. The evidence summary records this limit; all implementation and evidence PRs remain draft.
