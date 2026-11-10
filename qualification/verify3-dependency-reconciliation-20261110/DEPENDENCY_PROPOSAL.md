# Fixed-source joint dependency proposal

Immutable execution input is joint seed `dd42001783d87d2f5a591fe700544bda61f9c028` from #5694. It combines common `a2cd828aad47c56ac8c01dc2e423454eca7eafae`, exact Matrix vendor/wiring checkpoints #5688/#5689 and only the released-package pin-utils lock blobs from #5691. All 50 recorded VERIFY Python blobs are preserved. No CTRL branch or combined lock was imported.

The seed is deliberately unresolved: its pin-utils lock inputs still contain Matrix 0.18/vodozemac 0.10 while its reviewed source selects Matrix 0.19.1. Exact blob pins establish the input; they do not establish a usable locked graph.

The executor reuses #5655's bounded proposal logic. It checks the clean checkout, exact BASE ancestry, a four-file proposal allowlist and ten exact input blob identities. These include both lockfiles, both Matrix manifests, deny.toml, audit.toml, the no-suppression checker and its tests, and the original cargo-deny workflow. It verifies the official SQLx SQLite 0.9.0 archive checksum `488e99c397a62007e4229aec669a179816339afc6d2620ca6fa420dbee2e982c`, preserves every implementation byte and backports only the reviewed libsqlite3-sys upper-bound expansion to both manifests. Upstream source is `10462fa4414c6c7f1ed1d39bb31678e3b726878c`.

Proposed resolution requires rmcp 3.9.0, libsqlite3-sys 0.39.1, rusqlite 0.41.1, vodozemac 0.11.2 and no pin-utils. Cargo performs resolution; lockfiles are never hand edited. Retain full locked all-features metadata, validate every resolve node/dependency against its package identity, require one SQLite native-links package, reject bundled SQLCipher and confirm the preserved local aws-config and SQLx paths. The workflow regenerates and checks MODULE.bazel.lock, checks formatting of committed wiring/preparation changes, executes seven scoped consumer packages, retains the original policy guard and verifies the policy files are byte unchanged. It separately checks that none of the six current advisory IDs has been ignored, then runs the original pinned cargo-deny action.

After all test and audit stages, run final just fmt against the mutated candidate and retain its raw log and FORMAT outcome. No test runs after that formatting step. Recheck policy bytes and the original SQLx implementation hashes afterward; any formatter rewrite of preserved implementation bytes fails the stage. Full metadata and its stderr, final format evidence and every failure remain in the artifact. The earlier executor revision b084e01b9d2f8b7f3a75e592609b26d915a1d3c7 and run 42786545860 remain separately visible; this follow-up does not cancel or replay them.

Retained evidence includes the full candidate patch, both generated locks, resolved targets, stage outcomes and raw command logs, including failures. The original vendor provenance remains an imported-source record; proposed manifest changes are explicit in candidate.patch. The runner does not commit, push, merge or adopt its candidate.

Preserved Matrix behavior includes the physical matrix-sdk-0.18 store directory, passphrase handling and five-second startup limit. The existing migration tests and helpers are retained unchanged. Historical old-store/native receipts qualify their original source only. Default package tests do not execute the explicit ignored old-format producer/consumer phases; the result records those phases as OPEN_NOT_EXECUTED and old-store migration as unqualified. Those phases and full platform qualification remain open for this joint candidate. Event cache may be cleared; reverse migration and old-binary reopening are unproven.

Preparation validation: five synthetic archive/source-preimage tests passed before final layout formatting. The exact repository `just fmt` ran successfully for the new Python files with its locked Ruff 0.15.13; owning Ruff checks passed. YAML parsing, immutable action SHA checks and Bash syntax checks passed. These are preparation checks, with no Cargo resolution or native consumer/security result yet.

Dependency and security closure remains OPEN until the exact generated graph, unchanged policy, cargo-deny and consumer stages actually pass. Custom OAuth resolved-address policy and buffered HTTP response limits, full consumer/platform qualification, scientific gates and production adoption remain OPEN.


## Same-graph CLI provisioning after the original #5845 result

Exact parent is #5845 `130bb4c9297a4fc2fa8eb7ea7c7197f06c7b694f`.
Its original run 42893484349/job 130100373607 is retained FAILURE: all five
targeted auth-status tests explicitly pass, but the complete seven-package run
is 810 executed, 805 passed, five failed, nine skipped. Original artifact
13800472451 is 1,132,954 bytes / SHA-256
`60ed5b3930a3e3383580dd60e15546123016bf4a7275e4d2d40b9b7a5156a69d`.
All 13 internal result file hashes were independently verified. Its full raw ZIP
remains separately retained; no original test or failed attempt is overwritten.

The remote round-trip test explicitly fails before executor startup because
`cargo_bin("codex")` has neither Cargo nor nextest binary metadata. The same
`spawn_exec_server` is called by both remote timeout tests; their mock teardown
reports zero requests and can mask that setup failure. The seven original
selected library packages do not build/provide the `codex-cli` binary.

The existing workflow now builds only the real `codex-cli` / `codex` target from
the same disposable resolved graph with `--locked`. It verifies both locks stay
byte unchanged, retains Cargo's raw build output, and selects the single actual
binary artifact for the exact local CLI manifest. It records source, package,
features, executable SHA-256 and both lock hashes before exporting the absolute
`CARGO_BIN_EXE_codex` path through the existing runner environment. No PATH search,
prebuilt substitute, stub, install, credential or production binary is used.
The new CONSUMER_BINARY stage is required in the existing all-stages result.

All seven consumer packages, test selections, retries, original 500 ms/2 s
remote assertions, exact mock request counts, policy/deny, Bazel double-lock
checks, final formatter and official vendor byte assertions remain unchanged.
Consumers still execute after a binary-build failure, retaining their failures;
a failed setup cannot be reported as qualification. The original redirect-cycle
diagnostic, Matrix Initialization and FORMAT/vendor-byte failures remain open.
A new exact-head native result is required; source/YAML checks are not a CLI
build, remote-network test pass or independent scientific qualification.
