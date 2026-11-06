# Frozen JSON transport development: real execution, failed task quality

The fixed procedure completed without retries or additional model search. Its
single qualification passed, then all 16 planned episodes ran. The new decoder
admitted real SQL calls and four direct answers reached the exact verifier.
**No task achieved a correct delivered answer. No tool-using episode reached
the final verifier.** These negative results do not justify larger training.

This is development chosen after the two earlier formatting failures, using the
same disclosed eight tasks and two source clusters. It is not an untouched
confirmation or an NDU-versus-strong-baseline experiment. Earlier pilot outputs
and scores remain unchanged.

## Published before execution

The 34-input source freeze was created at 12:39:26.681838 UTC on 2026-11-06.
[Draft #4999](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/4999)
was created at 12:40:09 UTC with commit
`361c8fb5a2966d7008121ba92c6bc5c4ec128134`. Its freeze was read back before
qualification began at 12:40:28.782364 UTC. The fixed task run started at
12:40:48.908793 UTC and finished at 12:46:50.417376 UTC. This repository anchor
is not external preregistration.

The model remained Qwen/Qwen2.5-0.5B-Instruct at revision
`7ae557604adf67be50417f59c2c2f167def9a775`. The original worker, prompts, generation
limits, tools, parameter guards and verifier were unchanged. The separately
published adapter accepts only native JSON or one exact JSON fence followed by
the explicit stage schema; it does not repair, coerce or retry responses.

## Complete task results

| Arm | Planned | Delivered | Exactly correct | Model dispatches | SQL dispatches | Verifier dispatches |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Direct | 8 | 4 | 0 | 8 | 0 | 4 |
| One model-selected tool | 8 | 0 | 0 | 11 | 4 | 0 |

Direct had four answer-schema failures; its four delivered answers all received
verifier score zero. The tool arm had four parameter failures, two answer-schema
failures, one envelope failure and one tool failure. Three SQL calls returned
observations and one worker exited with code 1. No source-reading tool ran.
The zero task scores include rejected/incomplete episodes; those episodes were
not all semantically graded as wrong. See the full per-task table in the
[independent audit](evidence/independent-audit/AUDIT.md).

The qualification was one additional real response containing integer `[1]` in
an accepted JSON fence. It is outside task denominators. This run contributed
20 model responses including qualification; the three local procedures together
recorded 54. Their fixed parameters remained unchanged throughout inference.

## Actual clocks and resources

| Scope | Input tokens | Output tokens | Outer wall seconds | Child CPU seconds |
| --- | ---: | ---: | ---: | ---: |
| Qualification | 53 | 11 | 12.553637 | 19.042694 |
| All task episodes | 2,806 | 651 | 361.508770 | 515.200924 |

All counts remained within one qualification call, 24 task model requests,
eight tools and 16 verifier requests. No admitted request timed out. Every
delivered result met its real episode/global deadline. Decoder and cleanup work
remain inside measured host wall time; nested worker/generation times must not
be added again. Paid external model API calls were zero. Host monetary cost is
unknown, and positive monetary or lifecycle net benefit is not established.

## Independent audit and complete raw evidence

A separate internal reviewer independently read all 35 frozen remote files,
reconstructed each new payload/decoder/ledger/summary and checked real tool
stdout hashes, exact verifier outcomes and tokenization. Its first audit passed;
162 inputs, including all four earlier raw qualification/task runs, were
unchanged. The 494,032,768-parameter, 290-tensor fingerprint matched before and
after every response. This is internal evidence review, not external review.

[The original audit output](evidence/independent-audit/audit-attempt-01.json) has
SHA-256 `d769209047835e59abfab3d9b2ef06dbf6292a94d268114d202d54e586b00fa6`.
All 41 new raw files are preserved in the two lossless execution archives,
with exact per-file hashes in
[archive-index.json](evidence/execution/archive-index.json). A separate restore
produced byte-identical originals without model or tool execution. Restore to a
new directory using `python restore_execution.py --destination NEW_DIRECTORY`.

The audit deliberately does not infer a discarded worker stderr message or
replay a failed SQL query. It does not attest the host clock or unrelated host
activity. Four legal plans, three SQL observations and separate direct-answer
verification establish limited execution evidence. Full tool-assisted delivery,
semantic success, independent confirmation, novel algorithmic advantage and
positive net benefit remain unestablished. The earlier candidate's NO_GO
decision remains in force.
