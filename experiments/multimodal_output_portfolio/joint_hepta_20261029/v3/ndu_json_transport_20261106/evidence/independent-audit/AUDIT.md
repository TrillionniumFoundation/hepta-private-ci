# Independent internal audit of the JSON transport development run

The first audit attempt passed. It verified complete recorded execution and
preservation of the prior evidence. It did not establish task accuracy, NDU gain,
an independent task confirmation, or positive monetary net benefit.

The reviewer was `/root/json_audit`, separate from the runner author and the
coordinator. This is an internal receipt audit, not an external scientific review.
The earlier audit's exact BF16 bit-expansion method was reused explicitly.

## Source and qualification binding

The reviewer read the runner, published decoder, protocols, original Qwen worker,
transport/ledger, and SQL/source/verifier implementation. No source change was
requested. Static review and the existing ten synthetic wiring scenarios covered
public-only task projection, the unchanged tool guards, hard request caps, the
new qualification gate, decoder stages and completion deadlines. The scenarios
were read as synthetic wiring evidence, not counted as real model or tool work.

All 34 frozen source files plus the freeze itself were independently fetched
from immutable commit `361c8fb5a2966d7008121ba92c6bc5c4ec128134`.
All 362,916 bytes matched local files exactly, including SHA-256 and Git blob
identities. The actual publication and execution times were:

| Event | UTC, 2026-11-06 |
| --- | --- |
| Local prospective development freeze | 12:39:26.681838 |
| Git commit | 12:39:52 |
| Draft PR #4999 created | 12:40:09 |
| Qualification started | 12:40:28.782364 |
| Qualification finished | 12:40:41.335951 |
| Fixed task run started | 12:40:48.908793 |
| Fixed task run finished | 12:46:50.417376 |

The new single qualification response was an exact JSON fence containing the
integer array `[1]`. The auditor independently reconstructed its decoder result,
payload, output tokens, receipt and ledger, then checked the task run's reference
to this exact qualification result. Qualification is outside task denominators.
An ordinary draft timestamp does not constitute external preregistration.

## Observed task results

| Arm | Planned episodes | Delivered | Exactly correct | Model calls | Actual tool calls | Actual verifier calls |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Direct | 8 | 4 | 0 | 8 | 0 | 4 |
| One model-selected tool | 8 | 0 | 0 | 11 | 4 | 0 |
| Total task run | 16 | 4 | 0 | 19 | 4 | 4 |

All four admitted tool calls were SQL calls. Three returned observations; one
failed with a nonzero worker exit. No source-reading tool was launched. No
admitted request was a timeout, and no task was omitted. The four delivered
direct answers reached the exact verifier and all scored zero.

| Task | Direct outcome | Tool-arm outcome |
| --- | --- | --- |
| `chinook/artist_count` | Answer schema rejected | SQL returned; answer schema rejected |
| `chinook/genre_top_three` | Answer schema rejected | SQL returned; answer envelope rejected |
| `chinook/invoice_country` | Answer schema rejected | SQL returned; answer schema rejected |
| `chinook/longest_album` | Answer schema rejected | SQL worker failed |
| `cpython/quantiles_defaults` | Delivered; verifier zero | Plan schema rejected |
| `cpython/constant_regression_error` | Delivered; verifier zero | Plan schema rejected |
| `cpython/decimal_fallback` | Delivered; verifier zero | Plan schema rejected |
| `cpython/rank_defaults` | Delivered; verifier zero | Plan schema rejected |

The SQL failure receipt retains exit code 1, no stdout, and the transport's
`ValueError` classification. The selected query names `TotalTrackDuration`, which
is absent from the supplied public Album schema. Worker stderr was intentionally
discarded by the frozen transport, so this audit does not assert an observed
SQLite exception message or reconstruct one by rerunning the query.

## Time, resources and preserved failures

| Scope | Real model responses | Input tokens | Output tokens | Outer wall seconds | Child CPU seconds |
| --- | ---: | ---: | ---: | ---: | ---: |
| Qualification | 1 | 53 | 11 | 12.553637 | 19.042694 |
| All 16 task episodes | 19 | 2,806 | 651 | 361.508770 | 515.200924 |

The task budget was 24 model requests, 8 tool requests and 16 verifier requests.
All actual counts remained below those unchanged caps. Intent records precede
dispatch; terminal records bind the same request; host envelopes cover each
episode. Every delivered result completed before its effective episode/global
deadline. Decoder work and ledger cleanup remain in episode/outer wall cost.
Worker and generation measurements are nested within host time and must not be
added as separate monetary charges. External paid API calls were zero; actual
host currency cost remains unknown.

The auditor independently re-created every public request, accepted/rejected
decoder record, exact-verifier outcome, stage transition, request count, summary,
and relevant hash. Actual tool observations were checked against the recorded
worker stdout hash without running the tool again. Token counts and decoded
text were checked using the fixed local tokenizer. Raw safetensors bytes gave
the same 494,032,768-parameter, 290-tensor fingerprint as every model response:

`815634c0b4c921ad07b4a32437ff872342e745b15a386f6ca8f5a2d4974e0c13`.

All 162 audit inputs, including raw files from the four earlier qualification/task
runs, were unchanged before and after this audit. No earlier response was decoded
again, reinterpreted, rescored, or replayed. The audit performed zero additional
model forwards and zero model/tool subprocess calls.

## Evidence and limits

`audit-attempt-01.json` is the original first successful audit output; it was not
overwritten. Its SHA-256 is
`d769209047835e59abfab3d9b2ef06dbf6292a94d268114d202d54e586b00fa6`.
`remote-anchor.json` binds the 35 immutable remote files; its SHA-256 is
`fea285f37faf6f8727b0933d3712fbfa59e3d0e30b98616fb4d7f0dc81e3c68a`.

The audit establishes a recorded local frozen-model/tool/verifier path and
faithful negative results. It does not attest the host clock or unrelated
activity outside these runners, and package version/RECORD checks are not binary
attestation. These are the same disclosed development tasks in two source
clusters. Four legal SQL plans and three returned observations do not close the
semantic task-success, novel-algorithm, untouched-confirmation, or net-benefit
requirements.
