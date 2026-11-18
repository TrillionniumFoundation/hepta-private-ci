# E4 matched upstream results: full Circuit 0/6; one answer-removal recovery

The full predeclared run completed with the actual child returning zero after 1,034.621328 seconds. All 120 primary model calls, four A calibration calls and 130 total verifier calls are retained. The result does not establish Circuit necessity or a matched-budget cooperation gain.

## Actual results

F is the new `final_only` adapter and T is the new `all_actions` adapter from the matched-information E1 training. C is the older controlled-correction adapter and remains an unmatched secondary control. Each arm used the same six public-source tasks. These tasks were already accessed by E1; there are six task units, not 120 independent samples.

| Arm | Selected success | Model calls | Actual business executions | Format rejections | Input tokens | Output tokens |
|---|---:|---:|---:|---:|---:|---:|
| native_FF | 0/6 | 12 | 4 | 8 | 6,290 | 1,454 |
| native_TT | 0/6 | 12 | 9 | 3 | 6,193 | 1,371 |
| native_CC | 0/6 | 12 | 2 | 10 | 6,114 | 948 |
| native_TF | 0/6 | 12 | 8 | 4 | 6,193 | 1,293 |
| native_CF | 0/6 | 12 | 2 | 10 | 6,114 | 995 |
| native_TF_no_answer | 1/6 | 12 | 8 | 4 | 5,573 | 1,061 |
| native_TF_no_feedback | 0/6 | 12 | 8 | 4 | 5,808 | 1,259 |
| native_FF_retrieval | 0/6 | 12 | 10 | 2 | 9,831 | 760 |
| native_TF_retrieval | 0/6 | 12 | 12 | 0 | 9,817 | 736 |
| native_F_one_call | 0/6 | 6 | 2 | 4 | 2,486 | 686 |
| native_T_one_call | 0/6 | 6 | 4 | 2 | 2,486 | 596 |

Every first-call task score was zero. `native_TF_no_answer` recovered one task; the other second-call variants recovered none. Repeated first-slot F and T generations exactly matched their respective one-call controls at the token level.

## What the negative results localize

The complete TF route scored 0/6. Removing its answer edge while preserving the same real feedback scored 1/6 on requests `unquote_header_value`. The first T token output was identical in both arms; the receiving F input differed only by the removed assistant answer. With the answer present, F repeated the incorrect expectation that outer quotation marks remain. Without it, F generated an assertion that removes those marks; the actual original function passed and both wrong-output controls were rejected. [NEGATIVE_TRANSFER_CASE.json](NEGATIVE_TRANSFER_CASE.json) retains both raw outputs, actual requests and verifier receipts. This is one observed instance in which sharing the previous answer impaired repair, not a general estimate of negative transfer.

Retrieval improved formatting without improving task correctness. FF format rejections fell from 8/12 to 2/12; TF fell from 4/12 to 0/12. All retrieved runs still scored 0/6. A descriptive AST readout found that 22 of the 24 generated test statements exactly copied the retrieved A reference statement: FF 10/12 with two unparseable statements, TF 12/12. The copied tests were for a different function. [RETRIEVAL_COPY_READOUT.json](RETRIEVAL_COPY_READOUT.json) and its [source](RETRIEVAL_COPY_SOURCE.py) make this analysis reproducible without model or verifier execution. The retrieval instruction explicitly warned against copying reference expected values.

The same-model FF/TT controls, message ablations, route variations and actual Cell removals all executed as declared. Successful adapter transport and fewer format errors did not supply evidence of transferable task competence. Future work should address independent task reasoning and harmful reference copying; these results do not justify scaling the current Circuit.

## Model identity: two different hash objects

The serialized safetensors file and the loaded normalized parameter stream are different objects. Their hashes must not be compared as if they were the same file.

| Adapter | Complete safetensors file SHA256 | Loaded parameter-after SHA256 |
|---|---|---|
| F final_only | `8b1af8fac79c32b2456c4d1d23bd8662d736ebb191061a407a61076cb7286d54` | `f9c23acb0dcc56fce2f5466e727751737daf9dd87104164848431cb80229d529` |
| T all_actions | `8983207ec254dd74ce69141f8797672af2dc8fd131e2d638fadbb010022bfea9` | `e5da16c3256c27f06f42ecac69880ce8802a0eb3a87c05830d11c09477aa817f` |

File hashes were checked against the original manifests. Parameter hashes combine canonical normalized parameter name/dtype/shape with each actual contiguous tensor byte stream, and were checked against the original completed training receipts on every activation. Both adapters have 544,768 actual LoRA parameters. Cold-Predictor and shared-pool A outputs agreed exactly for both models before the first upstream call. No manifest or training source inventory was rewritten.

## Costs and boundaries

Primary evaluation: **120 model calls, 120 verifier calls, 66,905 input tokens, 11,159 output tokens, 69 business executions and 51 format rejections**. The A setup calibration added four model/verifier calls, 1,128 input tokens, 162 output tokens and four business executions. A-only reference preparation added six verifier/business executions. The full run therefore used **124 model calls, 130 verifier calls, 68,033 input tokens, 11,321 output tokens and 79 business executions**.

Two cold calibration predictors and one shared pool loaded three bases in total and five adapters. Pool load cost is shared, not counted again for every call. Owner-observed CPU usage was 1,007.690309 user seconds and 33.624390 system seconds for the child and its waited descendants. Those scopes overlap nested model/verifier timings and must not be added together. Equal call/token caps are reported; equal realized token cost, complete energy and monetary cost are not claimed.

The seven numerical and chat dependencies actually used by matched inference have the original E1 training-source hashes. Historical E1 source custody and this new execution-source custody are separately verified. The A calibration verifier is the original retained A verifier; the primary upstream verifier is part of the independently frozen joint runner. C training is unmatched. No authenticated users, external-teacher authorization, native owner adoption or settlement eligibility are established. E5 remains blocked on authenticated, authorized and deduplicated training sources.

## Validation and retained failures

Actual retained manifests and tensor shapes passed admission in the desktop runtime. The final CPU preflight passed 21 tests, including real BF16/F32 adapter loading and switching, tamper rejection, cleanup, Circuit message/Cell removal, and upstream original/control execution. `just fmt` ran afterward. A local preliminary tensor-test attempt lacked torch; it was not counted as a pass. Three earlier zero-model-call preflights are preserved under `preflight1` through `preflight3`: legacy source-context mismatch, an overbroad numerical dependency check that incorrectly included the separately versioned verifier, and an archive-path typo. The original legacy admission remained intact; the final runtime pins numerical/chat code separately from each verifier. The passing original CPU result and stderr are in `preflight4`.

Execution source: `41d273d06d0138ab4a747c5dc73bb2ee2a61e9ee`, parent joint candidate `e52c4f67cb58a65409256f7be263cfb49ac22557`. The plan was committed before any upstream generation. Readout and archive validation executed no models or task verifiers.

## Original archive

[RAW_EVIDENCE.tar.xz](RAW_EVIDENCE.tar.xz) is 992,168 bytes with SHA256 `cdd49201d8c62217ad2777cece0c33e3ec7043edb3a50718edf7527ad150d042`. It contains 1,334 members, including 1,332 indexed original files, full model requests/outputs, original verifier observations, frozen source, model manifests/training receipts, calibration, owner exit and the complete readout. Every indexed byte count and SHA256 was rechecked remotely and again after local transfer. The archive is pinned by exact path and hash in the repository blob policy; the global size limit remains unchanged.

The original [READOUT.json](READOUT.json) SHA256 is `2c58e290a21544637befe16ce8a3eb97024caa8879b3e20815cf08e11557cbc0`. [ARCHIVE.json](ARCHIVE.json), [INDEX.json](INDEX.json), [DEPLOYMENT.json](DEPLOYMENT.json), [RUN_SOURCE.py](RUN_SOURCE.py), [READOUT_SOURCE.py](READOUT_SOURCE.py) and [POSTPROCESS.py](POSTPROCESS.py) preserve the reproduction and custody chain.
