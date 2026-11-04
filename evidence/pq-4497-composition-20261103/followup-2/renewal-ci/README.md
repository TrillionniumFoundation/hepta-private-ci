# Retained PQ policy renewal results for the first follow-up

GitHub run [41609576436](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/41609576436), attempt 1, completed all four original lanes. Each lane executed exactly the 14 required dispatcher controls and the three required Agentd/App Server process controls, once per named case, with no selected failure or ignored case. The added queued/active cancellation control is included in the 14.

The tested source is `2d7506108fd1b7813d5afbe2bbb0aaf5d9460c6d`, tree `80562dbe724b082f388828b32fb305d036e8dff7`. The prospective merge is `21ceefde202d58ef60e937d637f725727a9fe086`, with base `3a81000aae08c658276958d678874aca4db5eedd` and that source as its two parents; its tested tree is identical to the source tree. Original command receipts and candidate records retain the before/after identities. All command identities are unchanged and clean.

| Runner and lane | GitHub job | Dispatcher | Product | Original linter, formatter and identity | Original ZIP artifact |
|---|---:|---:|---:|---|---:|
| x64 source head | 125827781308 | 14/14 | 3/3 | Passed | 13218678570 |
| x64 prospective merge | 125827781221 | 14/14 | 3/3 | Passed | 13218633572 |
| ARM64 source head | 125827780611 | 14/14 | 3/3 | Passed | 13219840861 |
| ARM64 prospective merge | 125827781107 | 14/14 | 3/3 | Passed | 13220715232 |

All four original ZIPs match their GitHub-provided SHA-256 and size. The independent review recomputed every command log digest and byte length, compared the literal required case sets with the raw logs, verified the original argument vectors, and compared the full before/after identity objects. `selected-tests.json` was also checked against the independently parsed raw cases. `review-4-lanes.json` contains the final review, complete original receipts and every ZIP member's digest. The earlier two- and three-lane review records remain snapshots of incomplete collection.

The original controls retain `--locked`, `--retries 0` and `--test-threads=1`. The immutable workflow retains a 90-minute job limit; the command limits remain 600 seconds for dependency fetching, 3,600 for dispatcher controls, 1,800 for process controls, 1,200 for the scoped linter, and 300 for formatting. The raw receipts report no timeout or output-limit overflow. `just fix --locked -p codex-hepta-evidence -p codex-hepta-agentd` and `just fmt --base 3a81000aae08c658276958d678874aca4db5eedd` completed successfully without changing the recorded source.

This is new runtime evidence for this exact source. The earlier run `41597536557` on `0baf43cf4bf8f953fff079725348de1d8f26434f` retains its actual zero observed executions of the original 13 dispatcher and three process controls. That earlier failure is not relabeled. The new cancellation control covers a queued waiter and an active owner paused after the protected read and before database mutation, for the two authentication profiles exercised inside the test. It does not establish all unknown-commit or whole-system recovery outcomes.

These results do not waive the separate effect-recovery failure, Bazel source-inclusion failures, or paired Chain deadline and CPU-budget failures. Whole-chain PQ security, full Hepta native acceptance, deployment and independent end-to-end qualification remain on hold. No qualification is automatically transferred to a later source revision.

The original archives are unmodified. `jobs-api.json` and `artifacts-api.json` retain the final official API observations; `api-provenance.json` records their source URLs and hashes. Temporary signed download URLs are not saved. The local review only read bytes, checked hashes and compared records; it did not rerun any original Cargo/Just command or native test.
