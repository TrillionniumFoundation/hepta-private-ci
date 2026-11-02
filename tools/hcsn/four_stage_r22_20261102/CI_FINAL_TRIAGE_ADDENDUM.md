# CI diagnostic addendum

This adds three checks on PR4649 head `94252595fa741ed331b9946d7a910b28c96e44cf`; the original nine-job triage is unchanged. The run41378736133 job snapshot now contains **12 failed checks**. No science/checker rerun, code change or workflow bypass occurred.

| Check | Confirmed result | Scope |
|---|---|---|
|125078966527 Windows nonshard label|`Confirm Windows Bazel test shards passed` reports upstream `failure` and exits1|Shard fan-in only; no additional test suite executed. The gate correctly propagates earlier failures.|
|125069635246 macOS ARM clippy|E0599 `append_qualification`; unwrap/expect lints; disallowed direct SQLx pool connections|Actual compile/lint failures; the broader lint set remains open.|
|125069635148 macOS ARM release|E0599 at `hepta-agentd/tests/plasticity_process_e2e.rs:115`|Compilation failed before any runtime result can be inferred.|

The macOS API error matches the previously documented feature-gated ledger method and generated Bazel integration-test dependency replacement bypass. The separate test-only candidate still requires hosted validation; no repaired CI is claimed. It does not address every lint failure or the previously recorded Windows native linking/runtime failures.

All three complete decoded logs were retrieved. Deterministic gzip files total **183311 bytes**, each below400000 bytes, with compressed and decoded UTF8 hashes in `CI_FINAL_TRIAGE_ADDENDUM_RAW_LOGS.json`. The JSON addendum preserves steps, precise job/head binding, error messages and source-line excerpts. Original raw evidence and prior diagnostic files were not rewritten.

