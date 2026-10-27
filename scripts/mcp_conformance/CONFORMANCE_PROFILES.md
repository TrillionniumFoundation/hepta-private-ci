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

Cross-profile baseline inputs fail before conformance starts. A new vendor baseline
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
