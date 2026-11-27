# Second actual task gate and portable runtime qualification

The old common executor admitted one exposed Ruff incident. This extension adds
the exposed codec false-green incident and explicit controller-pinned executable
profiles. Original source/test contracts remain fixed; a new runtime must pass
the same positive and negative qualification before any model proposal.

## Observed results

| Attempt | Qualification result | Meaning |
| --- | --- | --- |
| Codec 001 | 5/6 checks; one failed harness assertion | The partial-suite control actually selected 8 tests, while its assertion expected 1. The outer gate correctly refused the incomplete suite. |
| Codec 002 | 6/6 checks passed | The corrected negative fixture selects exactly 1 test and is refused. Other controls retain the original task gate. |
| Ruff runtime profile 001 | 9/9 checks passed | Exact runtime identity, original F401/E731 failure, 76-ID positive control and semantic/skip/boundary/timeout refusals. |

For codec, the original entrypoint exits zero with all 21 tests skipped when a
media tool is missing; the outer gate rejects that result. The known runner
refuses each missing-tool profile and passes each original ID exactly once in
the provisioned profile. Empty and partial runners are rejected. This exercises
the selected local workflow entrypoint, not the complete hosted workflow.

The seven original Python sources, workflow and MANIFEST are pinned to failing
commit `a88f2832f2a1a4d3734c1c88f76977dcc9b98ff1`. The MANIFEST was newly verified
at that exact failing ref; the earlier catalogue's fixed-ref evidence is not
rewritten. The fixed runner is qualification-only resolution evidence.

## Evidence

`summary.json` records source identities, both codec attempts, runtime profiles,
observed process costs and limits. `source-acquisition.json` records exact refs
and Git blobs. The qualification plans precede their respective executions.
`qualification-receipts.jsonl.gz` is deterministic gzip containing 73 original
result, semantic, qualification, driver and raw driver-output records. Each
record includes its original relative path, byte count, SHA-256 and full decoded
value. Nested command attribution appears in the complete result ledgers and
is not added again to waited-child CPU.

These are executor qualification controls, not independent task families or
predicted repairs. This work ran zero model queries and zero training updates.
Candidates remain trusted Python; filesystem/network isolation, parent-death
cleanup, complete OS identity and whole-system cost remain unqualified. No
future-task, compression or memory-over-retrieval claim is made here.
