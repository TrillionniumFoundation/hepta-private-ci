# Immutable-source actual-tool smoke bank

Eight authored tasks exercise real SQLite execution and bounded source-file
inspection. Sources are pinned snapshots of Chinook and CPython, with unchanged
upstream bytes and license notices. This removes a missing actual-tool integration
fixture. **There are zero LLM calls and no independent confirmation result.**

## Sources and independence

[sources.json](sources.json) records upstream commits, Git blob IDs and SHA-256:

- Chinook database commit `7f67772503d71ba90f19283c38e93923addb43fa`, using
  `ChinookDatabase/DataSources/Chinook_Sqlite.sql`; its permission notice is retained.
- CPython 3.12.0 commit `0fb18b02c8ad56299d6a2910be0bab8ad601ef24`, using
  `Lib/statistics.py`; the complete upstream license file is retained.

The logical SQL source remains `chinook.sql`, with its original byte count,
SHA-256 and Git blob ID. Its physical representation is `sources/chinook.sql.gz`
(152,396 bytes), using gzip with `mtime=0` and no stored filename. The manifest
keeps `local_file`, `bytes` and `sha256` for the logical original and adds
`storage_file`, `storage_bytes`, `storage_sha256` and `encoding` for storage.
Workers check the compressed hash, decode it, then check the original SQL hash.
The decoded bytes match the original SQL byte-for-byte. Execution needs no raw
SQL file; do not republish the larger plaintext copy. License files are unchanged.

The questions and answers in [tasks.json](tasks.json) are disclosed engineering
cases. Four questions share each source. They constitute **two source clusters**,
not eight independent samples. Each family has only one source cluster. No task
is an untouched confirmation unit, and `confirmation_eligible` is false. An
immutable public input is not automatically a representative deployment sample.

## Worker contract

The `sql` worker runs the actual pinned database in a fresh in-memory SQLite
connection. Database creation time is inside each measured invocation. SQL is
read-only: mutation, file attachment, PRAGMA access and extension loading are
rejected. VM-step, expression, column, cell, row and serialized-output caps bound
the supported queries. The `source` worker permits literal search or a bounded
line window in the pinned source file; it accepts no caller-selected path.
Sources are hash-checked before use. Workers remain ordinary local processes,
not a general adversarial security sandbox.

The public task interface omits expected answers, oracle requests and extraction
patterns. The verifier checks the exact JSON answer, including JSON types. For
the smoke run only, a clearly labeled scripted oracle knows the disclosed query
or search plan and extracts its answer from the actual tool observation. It has
additional knowledge and is **not a feasible model-performance baseline**.

The existing measured-clock adapter executes controller, tool and verifier as
separate subprocesses. Every invocation pays a declared fixture tariff. Those
tariffs exercise bookkeeping; they are not provider invoices or a lifecycle
economic model. Passing scripted tasks cannot qualify frozen-model behavior,
unknown-law learning, comparative net benefit or a scaling decision.

## Executed qualification

[qualification-final.json](evidence/qualification-final.json) contains five
behavioral checks and eight measured scripted episodes. Checks include attempted
SQL mutation, prohibited file access, VM exhaustion, oversized single values,
source-window validation and omission of private answers from the public task.
The existing bounded-execution test also verifies gzip integrity, zero mtime,
original-content identity, and reading in a temporary tree with no raw SQL file.
All eight scripted episodes delivered the expected answers. This storage stage
uses the original runner: its receipt binds worker, task, builder and source
manifest hashes and preserves timing and paid attempt events. It does not yet
include the separate runtime-source binding added by the downstream runner.
All results remain explicitly `real_llm_calls: 0`.

The pre-storage published receipt is preserved byte-for-byte as
[qualification-original.json](evidence/qualification-original.json). The current
final receipt is a fresh five-check/eight-episode run using compressed SQL and
the original runner. A separate downstream stage has its own runtime-bound
runner and freshly executed receipt; those results must not be substituted into
this stage's source manifest. New timings are rerun measurements, not a
performance comparison or scientific confirmation.

Earlier development receipts are historical engineering runs. Only the final
receipt in this stage is the accepted record for this stage's source hashes.

## Reproduce

From the repository root, choose a fresh result path:

```bash
python -m experiments.multimodal_output_portfolio.joint_hepta_20261029.v3.ndu_llm_confirmation.external_smoke.run_smoke --output /tmp/ndu-external-smoke-new.json
```

`build_tasks.py` deterministically regenerates the disclosed task file from the
pinned inputs. The worker CLI also accepts `sql`, `source`, `verifier` or
`scripted`, reads one JSON object on stdin and emits one JSON object on stdout.
Live-model controllers may receive only public tasks and registered tool outputs.
A fresh model/task/price freeze and source-independent confirmation bank remain
required before running the separate scientific acceptance gate.
