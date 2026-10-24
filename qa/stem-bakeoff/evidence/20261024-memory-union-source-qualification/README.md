# Scoped published-source qualification

This packet preserves two distinct results: hosted budget checks passed on
`bfe77f5cdd04935d8bbfba9199a725ffc48b69e7`, and the 22 original evolution cases passed in a fresh source-subset
capsule bound to union commit `3906c552223448a01702ac6eb3bc3c38c24cb5ab`. The local wrapper nevertheless exited
1 after its post-test module-origin collector failed. This packet retains that
failure and does not label the complete wrapper or whole union CI as green.

## Actual execution and identity

| Scope | Exact source | Actual outcome |
|---|---|---|
| Hosted budget component | `bfe77f5cdd04935d8bbfba9199a725ffc48b69e7` | 29/29 tests, zero skips, 2.476 s; job success |
| Local union evolution cases | `3906c552223448a01702ac6eb3bc3c38c24cb5ab` | 22/22 cases, zero skips, 3.254 s; then post-test collector error, outer exit 1 |

The hosted tree is `602242090763af109ea782b4e6e03980494b4056`; run
[40101978822](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/40101978822),
job 120895835857, artifact 12562558636. The original ZIP is 1,554 bytes with SHA256
`6a7a240d31e2c63dfa0e2da65260e0122fa4d92e5f28779b75c080699028b7b6`. All three ZIP members were checked against their
receipt and extracted bytes. All recorded job steps, including source unchanged,
completed successfully. These component results are not reassigned to the union.

The union tree is `a797406d71b8c425317659116982e7568f3c04f4`. Its GitHub commit/tree and all 222 subset blob pins
were independently read and compared; the recursive tree response was complete.
The capsule contains 190 Python files and 32 supporting files, 1,664,185 bytes.
Exact matching bytes came from 210 files in the distributed candidate and 12 in
the native candidate. No additional root fixtures were needed. This is a source
subset in the real relative script layout, not a full Git checkout.

Budget's local 29-case suite was cancelled before discovery or execution when
its actual hosted success became available. The recorded pre-run amendment kept
only evolution's 22 cases: four source/budget boundaries, nine stub dispatch and
deadline checks, three source/queue/scoring checks, and six actual-owner topology
checks. Real sibling `BudgetLedger` and `ParametricOwner` path guards execute
inside these unchanged tests; no source or test was edited to obtain a pass.

## Local runtime and retained failure

The fixed Python runtime was used through its original path after its library
files had been moved byte-identically to RAM. The complete relocation receipt
is retained losslessly compressed, with an external original-byte SHA. This
suite needs Torch 2.5.1+cpu and safetensors for an existing 8-byte structural
tensor fixture. It performs no model fit or generation; it is not all-stdlib.

The actual command, environment overlay, PID 534106, stdout/stderr,
wall/CPU measurements, and cgroup observations are retained under `execution/`.
The process wall time was 3.876109 seconds. No timeout or
OOM occurred. The only recorded subprocess command is the unchanged pure-Python
sleep used by the 0.15-second deadline test. No local suite was retried.

After `Ran 22 tests in 3.254s / OK`, the added collector resolved Torch's virtual
relative `__file__` value `_ops.py` against the capsule source directory and
raised `FileNotFoundError`. The complete traceback, failure JSON, and outer
exit 1 are preserved. `execution/evolution-result.json` was never produced;
a completed dynamic import-origin summary cannot be reconstructed or claimed.
Source hashes before and after execution match all 222 published blob pins.

`proposals/module_origin_collector.py` separately proposes explicit unresolved
records for virtual, relative and missing origins. It was not wired into the
executed driver, imported, tested or validated. The actual failed driver remains
unchanged and bound to the launch receipt.

## Evidence access and limits

Verify [source-qualification.tar.gz](source-qualification.tar.gz) using
[evidence-manifest.json](evidence-manifest.json), then extract the archive root
`memory-union-source-qualification-20261024/`. [members.jsonl](members.jsonl) lists every payload file.
[audit.json](audit.json) reports the independent raw-log/ZIP/source comparison.
The archive includes exact source bytes, original hosted evidence, all local
receipts and failures, both executed drivers, and the unexecuted proposal.
It excludes installed runtime/model binaries and unrelated QA archives.

This supports the specified source-subset mechanisms and sibling dependency
layout. It is not whole-union CI, native/Rust acceptance, distributed-host
acceptance, a complete dynamic import attestation, or production qualification.
No A/B benchmark, model score, task denominator or historical result is changed.
