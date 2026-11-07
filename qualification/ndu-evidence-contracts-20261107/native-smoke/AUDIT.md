# PR #5302 native CI archive audit

## Result

This run contains freshly executed native wiring evidence **and retained original owner receipts**. It is stronger than a historical test-name readback. It remains an engineering smoke and posthoc replay of a small completed run; it does not complete #5198, establish a beneficial model update, or authorize adoption.

The original GitHub artifact was downloaded and inspected without executing its contents. Its 24,623,356 bytes match SHA-256 `38553e5d20df40515e6931fb38927bc5c4abd5804862386885f5c8025bd760c1`. The archive contains 218 files (28,775,947 uncompressed bytes).

## Source and hosted run binding

| Field | Value |
| --- | --- |
| Repository / PR | `TrillionniumFoundation/hepta-private-ci`, #5302 |
| GitHub run / attempt | `42367881449`, attempt 1 |
| Job | `128390182669`, NDU v6 neural rollout smoke |
| Source head | `1e869d455fe2fb53b5221b84bc0a27e190b09ab2` |
| Actual tested prospective merge | `a805b3e4a419b861a8b1ef1c669678ab208dbfc2` |
| Source and tested tree | `34d4cff5f537c83eb3a4d15cdb0acece6f3f35a8` |
| Merge parents | `e23dfea486025e09d7e11dd17ea0852d6e3e89d0`, then source head |
| Artifact | `13573450979`, `ndu-v6-smoke-42367881449-1` |
| Created / expires | `2026-11-07T11:43:15Z` / `2026-11-21T11:43:13Z` |

GitHub's step readback reports every step successful, including actual generation, trained checkpoint replay, terminal owner and paired owner execution. All 21 archived command receipts bind the same clean before/after tested commit and tree. Their exact log bytes and SHA-256 values were checked against the retained originals; all matched. The command receipts count 99 Python tests, 236 native tests, 70 generation contract tests, 5 generation owner tests, 1 trained generation owner test, 5 terminal lane tests and 1 paired owner test. These are execution checks, not independent training replications. The trained owner selection intentionally filters out the other four generation tests, which already ran in the prior owner command.

Sources: [job](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/42367881449/job/128390182669), [original artifact](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/42367881449/artifacts/13573450979), [source commit](https://github.com/TrillionniumFoundation/hepta-private-ci/commit/1e869d455fe2fb53b5221b84bc0a27e190b09ab2), [tested merge](https://github.com/TrillionniumFoundation/hepta-private-ci/commit/a805b3e4a419b861a8b1ef1c669678ab208dbfc2). Machine readbacks are retained in `source-bound-readback.json`.

## What is retained

| Executed path | Original payloads retained in the ZIP | What they establish |
| --- | --- | --- |
| Generation owner: legacy, conditioned, controlled | Three `execution.json` files and corresponding `inference.journal` files under `owner-fixture/` | The registered driver invoked the real Python/Torch model; raw process stdout, PNG bytes, caption, model/request hashes and measured costs survived. The durable inference owner settled and recovered the execution. |
| Failed and indeterminate generation | Two more `execution.json` + `inference.journal` pairs under `owner-fixture/` | The deliberately incompatible loader case records exit code 1, stderr and host cost; the timeout case records `timed_out=true` and its measured cost. Failed evidence was retained. |
| Trained checkpoint owner replay | `trained-owner-fixture/controlled/owner-evidence-xOMyuB/{execution.json,inference.journal}`, `provenance.json`, `verification.v2.json`, fixture JSONs | The completed run's trained checkpoint and recorded actions were replayed through the native inference lifecycle; raw output hashes match the recorded source row. This is a replay, not an online native controller trial or a new quality observation. |
| Terminal owner import, freeze, fit and recovery | `terminal-owner/terminal-owner-evidence-gMfnKX/{evidence.json,ledger.bin,witness.bin,candidate.bin,artifact-registry.bin}`, plus original fixture | Seven observed terminal actions produce 14 ledger records (decision/outcome pairs), seven fitted cells and eight admitted candidates including the explicitly unsupported, unobserved abstain option. Candidate/registry bytes were persisted and reloaded and the owner-derived fit was recovered. |
| Paired owner | `paired-owner/paired-owner-evidence-FqmUMe/{evidence.json,holdout.bin,signed-owner-decision.txt}`, plus original fixture | A fenced holdout owner durably consumes before release, derives statistics, produces three local role signatures, rejects altered outcomes and recovers idempotently. One unique consumption record survives the tamper/retry checks. |
| Actual native rollout evaluator | `run/native-receipts.json` and `.jsonl`, `native-binary.sha256`, original `ndu-generation-rollout` executable | Eight receipts name `native_policy_evaluator=true` and pin the actual executable. Every receipt has `authority=DENY_ALL`, `production_authority=false`, `observation_attestation_verified=false`. |
| Completed bounded run | `run/{protocol.json,rows.jsonl,summary.json,status.json}`, all 56 image/caption outputs, forecast/selection/fit summaries and source pins | One training seed (17), two training configurations, seven policies, one budget (64), two future and two retention cases yield 56 rows. Images and source identities are constructed MNIST pair reconstruction/relation-caption tasks. |

The generation test explicitly uses `tempdir_in(fixture.artifact_root).keep()` and writes the process receipt before settling and recovering the durable inference journal. The terminal and paired integration tests likewise use `.keep()` inside their exported fixture roots. These originals are consequently present in the uploaded archive; their temporary-looking directory names do not mean they were deleted.

Frozen source: [generation owner](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/1e869d455fe2fb53b5221b84bc0a27e190b09ab2/codex-rs/hepta-infer-worker-host/tests/generation_owner_execution.rs), [terminal owner integration](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/1e869d455fe2fb53b5221b84bc0a27e190b09ab2/codex-rs/hepta-agentd/tests/generation_terminal_owner.rs), [paired integration](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/1e869d455fe2fb53b5221b84bc0a27e190b09ab2/codex-rs/hepta-agentd/tests/generation_paired_evaluation.rs).

## What remains test-only or absent

The extra generic `terminal_cell_owner::real_owner_decision_outcome_freeze_fit_registry_reload_and_withdrawal` regression uses the separate support `Fixture`, whose root is created under `std::env::temp_dir()` and whose `Drop` removes that root. Its original temporary ledger/artifact bytes are absent from this archive; its PASS is retained in the terminal command log. This does not negate the separate, retained `generation_terminal_owner` ledger above. The generic subset tests are test evidence rather than another measured source cohort. See the frozen [support fixture](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/1e869d455fe2fb53b5221b84bc0a27e190b09ab2/codex-rs/hepta-agentd/tests/support/terminal_cell_owner.rs).

The terminal and paired importer test executables are identified by their own SHA-256 fields (`6defac2223de3c1b846fb2b6843617818100a6d50413eb691cb4f55ade1bbf03` and `065f6589f21beeae75e9dcbf6c7d3ef1a05a5e5579bdf7d5e396dfe3230a9729`); their executable bytes are not individual entries in the archive. The separately built `ndu-generation-rollout` executable is retained in the full archive and was independently hashed here.

`signed-owner-decision.txt` is an original persisted **Debug-text witness** of the typed signed decision. Its SHA-256 equals the publication digest, and the test compares its bytes against the recovered typed owner derivation. The source explicitly refuses to treat Debug text as a trusted decoder. It is not a portable production deserialization receipt. Its signatures use deterministic local fixture keys and three local role/controller identities. The paired evidence says `external_observer_authenticated=false`; the terminal evidence says `production_authenticated=false`. Neither proves an independently authenticated external observer.

No formal NoUpdate learning-iteration result or actual same-model next-task handoff is established by these generation/fit/paired receipts. The files do not complete the `OwnerDrainedSameModel`/NextUse evidence required for a deployed learning contract. Nothing here authorizes a V5 zero-delta operation, positive-gain reward or adoption.

## Experimental and cost limits

The retained protocol declares `mode=mechanism_smoke_only`. The paired owner selects two future source cases, one fixed training seed, one candidate (`risk_aware_recursive`) and one baseline (`fixed_dev_tuned`): exactly four previously observed rows. The owner does not re-score them. It carries a posthoc witness of the original combined row receipt and Audit-B bytes, with no original separate signed observation.

The paired loss and factual-error differences both have mean 0 and interval [-1, 1]; `observed_thresholds_pass=false`. It uses a 64-comparison engineering profile, explicitly different from the original registered family32, conditional on frozen models and independent source pairs. `new_scientific_samples=0`, `previously_observed_engineering_only=true` and `qualification_or_promotion=false` are explicit. Terminal import likewise declares zero new scientific samples and does not fabricate an eighth abstain outcome.

The broader smoke run has two future and two retention cases, with only one independent training seed. Those rows and fixed episode cases are not independent training repeats. The two training configurations in this v6 run are `supervised` and `terminal_entropic_ndu`; this is not the Ordinary/Hepta × Light/NDU factorial across frozen and joint regimes required by #5198. It does not cover the five real task families, powered confirmation or independently authenticated evaluation.

Costs remain attached to their original scopes. The trained replay records 9,190,730,452 ns host cold-process wall time, 4,514,891,651 ns worker wall time and 4,514,614,359 ns worker CPU time, while the original resident complete row records 19,315,948 ns. These are different execution boundaries and must not be substituted for each other. All command timings and intentionally failed/timeout process receipts are retained. The run reports no physical energy measurement (`energy_joules=null`) and no observed physical media synchronization. This archive is not a claim that a deployment or the full research campaign has a closed resource ledger.

## Independent byte checks and small evidence packages

`verification.json` records successful checks for all 21 command-log hashes/sizes and source bindings; the accepted original rows and canonical protocol/summary digests; all 21 terminal source pins; all 16 paired source pins and four dataset-cache pins; fixture/publication hashes; the trained checkpoint, request and execution hashes; unique original-row membership; and byte-identical trained PNG/caption outputs. Canonical JSON digests are kept distinct from raw file SHA-256 values. Caption bytes contain no appended newline.

`payload-manifest.json` records size and SHA-256 for **all 218 original archive entries**. The small packages preserve all 203 non-model/non-dataset/non-executable payload files byte-for-byte (2,211,056 uncompressed bytes), including every original command receipt/log and the failed/indeterminate generation evidence. Each original retained file is below 512,000 bytes. The 15 omitted large/runtime files are individually enumerated and hashed, and remain in the downloaded full archive. Their omissions are explicit, so the compact packages are an auditable receipt subset rather than a self-contained replay installation.

The compact packages split owner evidence from run/environment evidence so each ZIP remains below the existing 512,000-byte repository limit. `package-index.json` gives each archive's SHA-256, size, payload count and membership. Derived readback, manifest and verification files have an `audit/` prefix inside the packages. No original payload was reserialized or modified. Exact frozen source files and their Git-blob/SHA-256 pins are retained separately under `source/` and `source-manifest.json`.
