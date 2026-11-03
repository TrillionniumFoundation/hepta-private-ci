# Hepta PQ authority role-key separation: source-bound component validation

The role-key patch was published at 88cdc9c942dff6789efcb854d1e1eb0310fcc18e.
The completed native and static observations below bind exact descendant
f5be46914c1a6516049871680c68108a7279adf7, tree
6562cf35ff131944dfb95015d5615af2ab3b8477. Both source manifests are clean;
all 11,221 tracked paths exist and the three role-patch file hashes are unchanged.

| Observation | Actual result |
| --- | --- |
| Original frozen f28 plus exact patch, sparse checkout | Exit 101 before any test: missing tracked docs/modules/MODULES.json required by include_str. Preserved in f28-result.json and complete original logs. |
| Strict package-scoped just fix with locked dependencies and -D warnings | Exit 0; no source changes. Transitive sqlx-sqlite deprecation warnings remain in the raw log. |
| Default just fmt plus actual package-wide cargo fmt check | Exit 0; supported formatting checked and source remains clean. Stable Rustfmt's four warnings about the ignored nightly-only imports_granularity option remain in the raw log. |
| Original FinalUse selection on the published descendant | 11 passed, 167 reported skipped, exit 0; no retry/flaky line observed. |

The native command is:

    just test --locked -p codex-hepta-infer-worker-host --lib -E 'test(final_use_authorizer::)'

Nextest run ID: 4a0af584-feb7-4104-bcd8-00b12af13606, original local profile.
The retained request JSON files contain the full actual command, working directory,
and explicitly supplied environment. Rust is pinned to 1.96.0; the task uses its own
Cargo target, one Cargo build job, no incremental build, and debug information
disabled for dev/test compilation. Original native assertions, timeouts and the
selection expression were unchanged. No test count is inferred from compile output.

Exactly one added test function passed. It checks all six pairs of issuer,
revocation-feed, clock and frontier key reuse using canonical pinned public keys;
a future issuer key reused by another role; a mismatched claimed pin; and valid
independently keyed open/reopen with a preprovisioned future key. The complete
observed test-name inventory is retained in f5be4691-owner-result.json.

This is a selected component observation. The 167 reported skips are retained,
and the result is not whole-package, production, WAN, full-system rollback,
migration or whole-chain PQ-128 qualification. It does not establish independent
secret custody or the separately configured approver's role separation.
The original failing checkpoint is retained and is not relabeled as a pass.
