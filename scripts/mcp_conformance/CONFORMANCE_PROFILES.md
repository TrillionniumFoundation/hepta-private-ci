# Explicit conformance profiles and baseline migration

Every runner invocation selects `--conformance-profile`. `legacy491` retains the
original pinned 491 bootstrap, scenario policy, and historical baseline. It rejects
an arbitrary CLI override. Earlier reports without a profile are interpreted only
as historical 491 metadata. Their executable was not verified by this new gate;
their recorded bytes and the original baseline remain unchanged.

`vendor-c37-sdk132-v1` requires the canonical vendored CLI and the execution gate in
[EXECUTION_IDENTITY.md](EXECUTION_IDENTITY.md). Verification runs before any product
process and again after the full capture. A changed source, output, or installed
peer graph fails the run and regression gate. Reports record the actual c37 ref,
descriptor, source/patch/lock hashes, output identity, and observed runtime. The
stable execution identity is retained in compact baselines; local paths and Node
patch versions are observations, rather than baseline portability requirements.

Cross-profile baseline inputs fail before conformance starts. Every vendor baseline
input is checked for the same preservation rules as extraction, before starting a
verifier or product child. Removing required passing checks, a case, a scenario,
or a remaining failure, or adding a new failure fails this preflight. A new baseline
is created from a complete authenticated capture, through `--write-baseline` or
`--extract-baseline`. Both paths enforce the original baseline's exact hash, every
original passing identity, all existing case/scenario coverage, and no added
failure identities. The ten metadata-var3 checks repaired by the original 85f
implementation must pass and become required passing checks. Remaining failures
may decrease and stay visible. The original 491 baseline is never rewritten.

For example, after a full vendor capture:

```sh
python3 scripts/mcp_conformance/run_codex_compliance.py /path/to/codex \
  --conformance-profile vendor-c37-sdk132-v1 \
  --baseline-report /path/to/complete-vendor-capture.json \
  --extract-baseline /path/to/candidate-vendor-baseline.json
```

This migration preserves check identities; it does not claim that 491 and c37
upstream oracles are equivalent. Existing checks, rules, scenarios, timeouts, and
transport ordering are unchanged. Metadata validation of an external report is
not proof that the report was executed. Keep the actual command, source snapshot,
binary build source and hashes, raw result, and before/after identity records when
qualifying a concrete run. A passed regression gate still exposes known protocol
failures and does not establish full MCP or production authorization compliance.

## Measured vendor baseline

`regression-baseline-c37-sdk132-v1.json` was extracted from the full fa54dc92
capture using the retained GNU `dev-small` Codex built from
`85f0216d1e14922cced6e334e5cdb81b705fb63d`, SHA-256
`b350868bfd7f37564067f710e910f95a0384cb61abd059c7c7cc2ae3b756b880`.
The metadata/profile commit did not rebuild or change that Rust binary.

The real capture exited 1: four of six cases passed and two retained protocol
failures. Strict baseline extraction exited 0. It preserves all 562 original
passing identities and the ten repaired metadata-var3 checks, adds 62 observed
passing upstream checks, and retains 18 failing identities. Most added checks
verify resource parameters and PKCE; their presence does not establish oracle
equivalence with the historical revision. The remaining failures concern scope
selection/escalation, pre-registered client authentication, and elicitation defaults.
The original automatic-auth policy stays explicit and unchanged.

The complete capture's SHA-256 is
`3437d9166e112b305d3216a7c1962c7481d33f045a07c24b3f6dfd2f8db6c783`;
the deterministic baseline's SHA-256 is
`c5045d5682f920bd9eca25a81f5d0d5160c12a0cd647d6c67ca88367365fd079`.
Full source maps and binary hashes matched before and after capture. This was a
component run in a linked checkout with shallow repository metadata and a real,
reachable original 995b ancestor. It does not satisfy the distinct complete-history
release-pair gate, and does not qualify Bazel, native-musl, or production execution.

The SDK now selects this execution profile and baseline explicitly. Its original
assertions, full-suite scheduling, and 300/180-second outer test budgets remain
unchanged. A new SDK run must bind its own actual result; the earlier 85f SDK
qualification does not automatically qualify this profile integration.
