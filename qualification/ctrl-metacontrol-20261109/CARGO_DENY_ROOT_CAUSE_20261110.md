# CTRL cargo-deny failure: original job-log reconciliation (2026-11-10)

This is **evidence reconciliation**, not a dependency fix or security qualification. It supersedes the earlier "log unavailable" observation in `GENERAL_CI_STATUS.json` without rewriting the original snapshot. The original job log was obtained via the connected GitHub `fetch_workflow_job_logs` action for job `129141400220`, workflow run `42611612873`, commit `332708b415427fb72b75253111de2ba15afc2d3f`.

## Confirmed blocking advisories from original cargo-deny output

| Advisory | Dependency in that lockfile | Failure | Safe remediation criterion |
|---|---|---|---|
| RUSTSEC-2026-0459 / CVE-2026-119375 | `libsqlite3-sys 0.37.0` | Bundled SQLite versions before 3.54.0 may disclose uninitialized page-cache memory with an adversarial database/WAL pair | Establish compiled SQLite variant and all database/WAL trust boundaries; upgrade via compatible `rusqlite` / `libsqlite3-sys >=0.39.0` where applicable; reproduce and verify against actual compiled version |
| RUSTSEC-2026-0457 | `rmcp 3.1.3` | OAuth metadata SSRF checking hostname text rather than resolved IP, including DNS rebinding-related bypasses | Upgrade to version incorporating fix (advisory states 3.7.0 boundary), validate resolver and redirects in local and remote transport modes |
| RUSTSEC-2026-0461 | `rmcp 3.1.3` | Streamable HTTP server tool-schema cache can grow without a bound, including rejected requests | Upgrade to fixed server implementation (advisory states 3.6.0 boundary), test forged unknown tool names and bounded memory |
| RUSTSEC-2026-0462 | `rmcp 3.1.3` | Streamable HTTP client accepts unbounded HTTP response bodies | Upgrade to `rmcp >=3.9.0` as the advisory specifies, test response size limits for JSON and error bodies across both supported clients |

The cited versions and details above are **what the original job reported** on November 9, not a claim that the current main still has the same dependency graph. Consult the pinned current Cargo.lock, Rust toolchain constraints, workspace API compatibility and live advisories before any remediation. Do not apply `cargo update` blindly, suppress an advisory, or call it repaired because unrelated CI passes.

The same log concluded `advisories FAILED, bans ok, licenses ok, sources ok`. It also emitted `advisory-not-detected` warnings for RUSTSEC-2026-0118, -0119, -0194 and -0195 in deny.toml. These warnings are not the four blocking vulnerabilities; determine whether they can be removed only after all workspace and target-platform dependency graphs and security policy have been reconciled.

## Work gates

1. Re-evaluate the latest source and main/PR heads with exact lockfile, Cargo features, Rust toolchain and job identity recorded. Check whether another security-upgrade branch already owns these fixes; do not race or overwrite it.
2. Resolve each advisory by an upstream-compatible, actually-built patched dependency or a rigorously demonstrated non-exposed build path accepted by the existing security policy. Preserve the original failing evidence and prove the new dependency tree.
3. Run `cargo-deny` and independent RustSec guards, plus targeted compile and runtime regression tests for SQLite, OAuth discovery and Streamable HTTP transports. Record source head, tested merge head, lockfile hash, command, outputs and all failures.
4. Re-check the earlier CTRL scientific blockers independently: six original #5450 WRITE_TEXT episodes with trajectory/launch/delivery/evaluator bytes, frozen prospective real CTRL comparison versus light and tuned fixed, authenticated labels, and fully matched lifecycle cost. Do not mistake fixture passes for those gates.

**Current status**: `HOLD_NO_GO`, `production_update=no-update`, `cargo_deny_root_cause_identified=true`, `cargo_deny_remediated=false`, `historical_5450_root_cause_established=false`, `prospective_native_policy_evaluation_performed=false`, `complete_cost_policy_gain_established=false`.

Source: [cargo-deny failing job](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/42611612873/job/129141400220). This note is a read-only forensic append; no lockfile, security suppression, runtime or adoption changes.
