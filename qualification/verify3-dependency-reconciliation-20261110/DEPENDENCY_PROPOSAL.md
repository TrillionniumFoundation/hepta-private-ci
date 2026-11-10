# Fixed-source joint dependency proposal

Immutable execution input is joint seed `dd42001783d87d2f5a591fe700544bda61f9c028` from #5694. It combines common `a2cd828aad47c56ac8c01dc2e423454eca7eafae`, exact Matrix vendor/wiring checkpoints #5688/#5689 and only the released-package pin-utils lock blobs from #5691. All 50 recorded VERIFY Python blobs are preserved. No CTRL branch or combined lock was imported.

The seed is deliberately unresolved: its pin-utils lock inputs still contain Matrix 0.18/vodozemac 0.10 while its reviewed source selects Matrix 0.19.1. Exact blob pins establish the input; they do not establish a usable locked graph.

The executor reuses #5655's bounded proposal logic. It checks the clean checkout, exact BASE ancestry, a four-file proposal allowlist and ten exact input blob identities. These include both lockfiles, both Matrix manifests, deny.toml, audit.toml, the no-suppression checker and its tests, and the original cargo-deny workflow. It verifies the official SQLx SQLite 0.9.0 archive checksum `488e99c397a62007e4229aec669a179816339afc6d2620ca6fa420dbee2e982c`, preserves every implementation byte and backports only the reviewed libsqlite3-sys upper-bound expansion to both manifests. Upstream source is `10462fa4414c6c7f1ed1d39bb31678e3b726878c`.

Proposed resolution requires rmcp 3.9.0, libsqlite3-sys 0.39.1, rusqlite 0.41.1, vodozemac 0.11.2 and no pin-utils. Cargo performs resolution; lockfiles are never hand edited. The workflow regenerates and checks MODULE.bazel.lock, checks formatting of committed wiring/preparation changes, executes seven scoped consumer packages, retains the original policy guard and verifies the policy files are byte unchanged. It separately checks that none of the six current advisory IDs has been ignored, then runs the original pinned cargo-deny action.

Retained evidence includes the full candidate patch, both generated locks, resolved targets, stage outcomes and raw command logs, including failures. The original vendor provenance remains an imported-source record; proposed manifest changes are explicit in candidate.patch. The runner does not commit, push, merge or adopt its candidate.

Preserved Matrix behavior includes the physical matrix-sdk-0.18 store directory, passphrase handling and five-second startup limit. The existing migration tests and helpers are retained unchanged. Historical old-store/native receipts qualify their original source only; the external old-format producer/consumer phases and full platform qualification remain open for this joint candidate. Event cache may be cleared; reverse migration and old-binary reopening are unproven.

Preparation validation: five synthetic archive/source-preimage tests passed before final layout formatting. The exact repository `just fmt` ran successfully for the new Python files with its locked Ruff 0.15.13; owning Ruff checks passed. YAML parsing, immutable action SHA checks and Bash syntax checks passed. These are preparation checks, with no Cargo resolution or native consumer/security result yet.

Dependency and security closure remains OPEN until the exact generated graph, unchanged policy, cargo-deny and consumer stages actually pass. Custom OAuth resolved-address policy and buffered HTTP response limits, full consumer/platform qualification, scientific gates and production adoption remain OPEN.
