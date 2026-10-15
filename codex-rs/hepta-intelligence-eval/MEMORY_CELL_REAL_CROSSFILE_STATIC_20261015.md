# MemoryCell real Git-source cross-file dependency trace — 2026-10-15

**Research-only. Model calls: zero. Downloaded repository code executed: zero. Production qualified: false.**

## Rationale and source provenance

The earlier fixed 9 function-declaration-location questions were solved 9/9 by a
small source-only declaration parser, and a rank-only rule solved 7/9. Those
outcomes make the original mechanical questions poor evidence of reasoning or
parameterized MemoryCell benefit. This continuation introduces a more demanding
*source-link integrity* measurement without inventing a new pretrained model
benchmark or calling original task tests.

Data are the exact historical six-repository Git object archive acquired in
[GitHub Actions #38320847158](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/38320847158)
from pre-existing source cut **2026-10-12 16:05 UTC**. Source ZIP SHA-256
`a4c7b9868461c11558546bd582796255cbca682c938a1704d62cd93a556406b4`;
separately executed binary reopen ZIP SHA-256
`59dee0a84099f6fb101dbfd5420c569f10c44a2d8a7b67c984e381edf4db9d36`.
The independent original source check asserts all 32 original Git blob SHA-1,
per-file SHA-256, 14 original commits and 1,558,460 source bytes.

## Completed static traces

Twelve original cross-file links from three **retrospective repository-name
proxies**, all within the previously flagged `evaluation` source partition:

| Source | Links | Link mechanism |
| --- | ---: | --- |
| CPython HTTP tests and `Lib/http/client.py` | 3 | `client.HTTPConnection` constructor-alias → concrete instance method definition |
| scikit-learn unit tests and original implementations | 6 | AST `from ... import ...` → call node → unique top-level `def` |
| Deno global/file-fetcher cache and `libs/cache_dir/cache.rs` | 3 | exact `use crate::cache::SYMBOL` → original reference token → exported definition |
| **Total** | **12** | **All import/use, call-site, and definition SHA-bound** |

Every row contains original repository, source paths and blob SHA, AST/test
scope or conservative Rust lexical scope, line numbers, and exact SHA-256 of
three original source lines. The program never executes downloaded code or
prompts a Reader. This is a *lower-cost, deterministic source reasoning null*,
not evidence of complete program semantics or independently verified task
success. The Rust subset is a deliberately limited literal-import checker,
not a general Rust parser, macro expander, dynamic dispatch analyzer or name
resolver. The Python analysis is syntactic and excludes local rebinding of
imported symbols and constructor aliases; it is not full dynamic data flow.

The independent audit checks original Git blobs again before linking, including
`train`/`selection` partition isolation. Mutation tests remove or forge caller
import, exact use-site, callee definition, constructor binding, raw Git bytes
or entire ZIP; all fail closed. An archived caller test is *not executed*:
`real_project_tests_executed=false` and `task_success_rate=null`.

The frozen model-free report is
`scripts/memory_cell/data/memory-original-crossfile-static-20261015.json`,
SHA-256 `555c85a878e7c6e7c2fa95efaccf4c3c3143e534e8e5a61a84d5b8b352a53ec7`.

## Reproduce without downloading or executing models

```bash
export MEMORY_REAL_SOURCE_ZIP=/path/exact-original.zip
export MEMORY_REOPEN_ZIP=/path/exact-independent-reopen.zip
export PYTHONPATH=scripts/memory_cell
python3 -m unittest discover -s scripts/memory_cell \
  -p test_memory_original_crossfile_trace.py -v
python3 scripts/memory_cell/memory_original_crossfile_trace.py \
  --source-zip "$MEMORY_REAL_SOURCE_ZIP" \
  --reopen-zip "$MEMORY_REOPEN_ZIP" --output NEW_REPORT.json
sha256sum NEW_REPORT.json
```

The original SHA source report is never overwritten or substituted with
invented model outputs. GitHub Actions downloads the two pinned archives,
executes the 18 fail-closed source and mutation tests, independently regenerates
the aggregate, and compares it byte-for-byte with the frozen model-free report.

## Decision and next experiment

All twelve registered static dependencies are reproducible, so a new Reader
cannot receive credit just for guessing that a familiar implementation method
exists. Stronger future work must hide the answer label and ask for **full task
success with both caller and callee evidence, original tests independently
run in an authorized sandbox, source-version correction, and actual cost**,
with same Reader/tools/token budget as strong RAG and the parser baseline.
No such new Reader/executable-project experiment is claimed complete here.

Source roots are three retrospective project-name proxies, not independently
certified N, and no future-source window, human evidence sufficiency judgement,
parameter-learning advantage, revocation/recovery or production admission has
passed. `production_qualified=false`, `independent_semantic_judgement=false`,
`full_lifecycle_tco=null`; do not merge to stable/production without existing
`blocking-ci`, Architecture and independent acceptance.

## Offline execution extension — exact original CPython HTTP implementation

The separate, SHA-pinned original CPython \`Lib/http/client.py\` source is
re-executed in an isolated Python 3 subprocess with CPU and memory bounds,
in-memory fake sockets and outbound network calls disabled. The original
\`HTTPConnection\` implementation passed three specified byte-level behaviors:
request (111 bytes), putheader (92 bytes), and send (14 bytes). Before loading
the original source, the verifier independently reopens the same six-repository
Git ZIPs and validates all 12 prior static call/import/definition chains.

The fixed worker source is independently hashed, all three captured byte
streams must match expected HTTP protocol bytes, and the report explicitly
marks full upstream CPython tests, third-party project tests, authenticated
independent hosting, other languages, model calls and production qualification
as **not performed**. Local 12/12 runtime negative tests and pre-existing
18/18 original-static tests passed. Immutable output SHA-256:
\`b847f79630c02e48aa174021a6c668f7882e90ee8d383302cef8b14374152f4b\`.
The exact-head hosted CI result and mandatory standard gates remain required.
