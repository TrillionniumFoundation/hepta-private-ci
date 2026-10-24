# dot-native continuation, exact #3617

Source: d1619f1d2dd433f958d76143309011c73b4c5cf5, tree 651eb338b43dad625028f13c0ba536372faa7674. Real shallow Git checkout obtained from normal GitHub origin; plugin metadata independently confirms identity. No reconstructed/fabricated Git history. No source edits.

Rust 1.95.0 installed from official static.rust-lang.org, rustup-init checked against official SHA256. Isolated CARGO_HOME/RUSTUP_HOME, no credentials or security settings changed. just 1.51.0 and cargo-nextest 0.9.103 official GitHub releases verified against release API digests.

Local fixture preparation: 16/16 passed. Nextest wrapper: initial run without tool PATH retained (3 passed / 7 skipped); corrected isolated PATH run 10/10 passed, no skipped. These are dot results, not inherited cloud results.

Production Agentd default-feature executable build PASSED in 9m09s, jobs=2, incremental=0, dev debug=0, --locked, no whole-workspace/all-features. Warnings retained. Binary SHA256: 5443883d026bcd8f0147aa5e543eb9120ecf45c8c4066c27d05101cf95d08fde. Seven real-process configuration rejection smoke cases PASSED: each exited 1 with the expected error, no writes in isolated home. This is a development-profile production-target executable, not an optimized release-profile build. Scoped real-Agentd execution PASSED: 14 research owner library cases plus 9 runtime_shutdown_outcomes integration cases, 23/23 passed in 2.138s, with 174 library tests filtered out. This selected success is not a full-library pass.

A subsequent unchanged full default-feature library attempt on dot ran 188 tests: 184 PASSED, 4 FAILED, 0 skipped (5.905s, exit 100). All four failures were Unix socket bind/probe EPERM/PermissionDenied, including the configured retry. These results differ from the earlier cloud environment and must not be replaced by its 188/188 pass. See socket-environment-blocker.md. A one-shot normal escalation diagnostic could not start because the execution wrapper failed; no diagnostic test ran. Complete library acceptance remains BLOCKED.

The standalone Agentd executable validates fleet configuration before argument parsing and does not implement a standalone --help. Missing fleet under --help is expected rejection, not CLI-help coverage. Research task Head owner is deliberately not wired into production daemon startup; separate library smoke is required.

SHADOW_ONLY / DENY_ALL unchanged. No private 2560-row replay, live vendor, production authorization, deployment, merge, or source-authentication/revocation qualification.

Reproduction layout: `production_config_smoke.py` is an unchanged copy of the executed driver. Restore it at the workspace root (beside `repo/`, `target/`, and `evidence/`), rather than running the archived copy from within this evidence directory. `invocations.json` records exact commands and environment values; replace only the workspace prefix to relocate the replay. Original raw logs and their failures are retained. Absolute workspace paths in logs are environment metadata, not private assets.

Artifact identity recheck: the integration test build temporarily replaced target/debug/codex-hepta-agentd with SHA256 9457c9c3cca0fb5bc023c7d5f7960d02fb420ff276296e022cf24575e905e2f9. It was retained separately, then the original production-target command plus --offline restored the original exact SHA256 5443883d026bcd8f0147aa5e543eb9120ecf45c8c4066c27d05101cf95d08fde in 0.91s, exit 0. The restored bytes exactly match the earlier seven-case smoke target; no new smoke outcome is invented. Both binaries are retained locally and are not included in the evidence publication. Source remains unchanged.
