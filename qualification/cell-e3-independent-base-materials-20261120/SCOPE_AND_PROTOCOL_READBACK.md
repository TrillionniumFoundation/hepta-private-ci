# E3 scope correction and frozen protocol readback

## Technical state

**The additional SmolLM2 weights are incomplete. The previously completed T2 service evidence remains valid historical evidence and is not erased by the desktop material inventory.**

This addendum corrects the scope of statements in [FINAL_STATUS.md](FINAL_STATUS.md) that could be read as saying the whole system had only a Qwen2.5 teacher. The earlier inventory covered six specified desktop SFT directories. Within those directories, 26 manifests represented one Qwen2.5 base and eight adapter parameter sets. It was not a census of all hosts or services. The initial files and their hashes remain unchanged; this explicit correction supplies the current interpretation.

The existing [E3 diagnostic in #6705](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/6705) already executed a different checkpoint and architecture, Qwen3.8-Flash-Next-Uncensored-IQ4XS-NGQ4. Both existing teachers are from the Qwen family. SmolLM2 would be an additional independent base for the inspected desktop setup; it is not the first historical second-teacher attempt.

No new model request, model load, forward pass, training update, native task or acquisition owner was added by this scope review. Continuing the already authorized research does not require another user permission request. The remaining constraints are technical readiness and the unchanged accounting of each frozen experiment. The prior Range plan records a preparation-only subtask; it has not run.

## Exact existing models and limits of inspection

| Material | Evidence observed | What it supports |
|---|---|---|
| Desktop Qwen2.5-Coder-1.5B-Instruct at `2e1fd397ee46e1388853d2af2c993145b0f1098a` | Prior exact local inventory, complete standalone weight, model manifests and Apache-2.0 license bytes | One admitted SFT base in the six inspected desktop roots; multiple adapters are not multiple independent bases |
| ai395 Qwen3.8-Flash-Next-Uncensored-IQ4XS-NGQ4 | Original full 98,403,356,224-byte hash `cedf1e08063f6df77926e1169f67b327dcc6301b5b329589615bdf09d4895f7e`; fresh stat identity exactly matches the original device, inode, size, mtime and ctime | The original T2 material remains at the known path; this review did not rehash 98 GB or attest a current serving process |
| ai395 `qwen38-flash-next-mtp-Q4_K_M.gguf` | 2,790,341,728 bytes; bounded header says `Q38Fn Mtp Src`, architecture `qwen4exp`, 37 tensors | An MTP-named artifact associated with the same architecture; no admitted independent base provenance, complete-payload digest or clear independent license was established |
| Desktop SmolLM2-1.7B-Instruct at `31b70e2e869a7173562077fd711b654946d38674` | Nine support files complete; only 255,852,544 of 3,422,777,952 weight bytes retained after the one 895-second attempt | Additional weights incomplete; no SmolLM2 execution or complementarity measurement |

The fresh host inspection was limited to the already known `/home/qq/local-llm/models` directory. It contained only the two GGUF files above and no adjacent README, LICENSE or configuration file. A bounded directory stat took approximately 0.00009 CPU seconds. A second read consumed exactly the first 65,536 bytes of each file, 131,072 bytes total, and approximately 0.00063 CPU seconds. Large metadata arrays stopped parsing; no tensor payload was parsed or hashed. Header identity does not establish full payload integrity. No credentials, private personal directories, server endpoints or inference workloads were accessed.

The large T2 header still reports a local Apache-2.0 label. The original frozen E3 protocol records its conflict with the upstream community license and the prior user-authorized private internal research scope. This review preserves that evidence; it does not resolve commercial rights from the embedded label. The MTP header does not establish a separately licensed and independently useful teacher. No additional complete independent base with clear provenance was established in these inspected paths; no claim is made about uninspected hosts or directories.

Original source and evidence are linked and copied in [scope/original-e3/PROTOCOL.json](scope/original-e3/PROTOCOL.json), [READOUT.json](scope/original-e3/READOUT.json) and [WEIGHT_IDENTITY.json](scope/original-e3/WEIGHT_IDENTITY.json). The original protocol and runner bytes match both the execution commit `16f21699a4cd661ed998333369f3734a572caf96` and evidence commit `5e027a1d0c49a2b1408e90491b4cc0bc1660725f`.

## Existing E3 budget and results remain fixed

The original protocol admits six original A tasks, exactly two T2 calls per task and twelve planned new model calls. All twelve have already run. T1's twelve corresponding calls were reused. There is no unused original call slot, and the original `training_on_new_outputs` is false. This review neither restarts that protocol nor converts it into a student-training budget.

The original outcome is T1 0/6, T2 1/6 and union 1/6. Union equals the better teacher alone, so gain over the best teacher is zero and mutual complementarity was not observed. The original twelve calls used 5,207 input and 2,398 output tokens; three reached the 384-token output cap. These failures remain in the evidence and are not repaired by rewriting the answer format or increasing the old cap.

The separately recorded four-task maintenance collection also remains: eight T2 calls, first success 1/4, final success 1/4, recovery 0/3 and preservation of the one success. It supplies no unused evaluation allowance. Its current progress entry is retained in [scope/CURRENT_E3_SCOPED_READBACK.json](scope/CURRENT_E3_SCOPED_READBACK.json); this review does not replace its original experiment identity or combine it with the six-task denominator.

These completed T2 diagnostics are separate from the original #6778 student evaluation's 56 new generations, 47 native executions, nine validation rejections and NoUpdate. SmolLM2 preparation and this review add zero to those counts.

## Concrete execution gaps in the frozen design

**1. The current evidence is teacher coverage, not multi-teacher student learning.** The original protocol explicitly has no training on new outputs, no student fit, no negative-transfer measurement and no B data sent. A union of successful teacher answers is a coverage diagnostic; it is not an executed learned selector or a new foundation model. Any subsequent student comparison needs its own immutable identity, exact teacher-output corpus, student parent, trainable parameters, objective and concrete accounting before execution. This addendum allocates no additional calls or updates.

**2. Information matching has a precise scope.** Both teachers received the same initial logical task and the same two-call opportunity, output-token cap and verifier opportunity. In the second call, each receives its own real preceding answer and its own resulting verifier feedback. Those histories are correctly policy-dependent and need not be byte-identical. A future comparison intended to isolate the value of native feedback or routing must freeze its common-prefix controls and its own-trajectory measurements separately before reading outcomes.

**3. Equal token or call caps do not make physical compute equal.** The two existing checkpoints differ in tokenizer, quantization, active parameters, hardware and server runtime. The original protocol explicitly marks physical compute unmatched and service/energy cost unknown. A later cost comparison needs measured service compute, memory and transport costs in addition to the recorded request count and client wall time. Hashing, startup and failed work also remain visible; nested windows must not be added as independent elapsed time.

**4. There is a concrete future admission hardening point.** The original protocol declares a 4,096 input-token bound, but static inspection of its HTTP runner shows that the runner never reads that field. The actual twelve response receipts report at most 796 input tokens, so no historical input-cap breach is alleged. Before a later batch, its runtime should admit the exact native chat template and tokenizer and reject an over-budget input before dispatch, then retain actual usage afterward. The old answers and scores remain unchanged.

**5. The current desktop runtime does not admit the SmolLM2 architecture.** Its existing `causal_probe_v3` material gate requires `Qwen2ForCausalLM` and `model_type=qwen2`; the pinned SmolLM2 config is `LlamaForCausalLM`/`llama`. Completing the weight download alone would not make that execution path compatible. A separate explicit model profile must bind the complete file digests, tokenizer, native chat template, special tokens and action extraction rules before using the additional base. Merely relaxing the current Qwen identity check would weaken admission.

**6. Historical file identity is not a current service freeze.** Fresh stat matches the original T2 weight identity, but this review did not query or bind the current service executable, process start identity, template or slot state. Those must be admitted again for any genuinely new future run. The original completed twelve calls remain bound to their original service freeze. The new MTP artifact cannot silently substitute for a teacher or modify that original identity.

The read-only facts and checks are machine-readable in [scope/PROTOCOL_STATIC_REVIEW.json](scope/PROTOCOL_STATIC_REVIEW.json). They identify concrete work to make another experiment executable while retaining all prior budgets, successes, failures and NoUpdate decisions.
