# V26 — original pretrained public Qwen forward, attention-mask and source-guard repair

**Research / Draft / Shadow only / HOLD_NO_GO / DENY_ALL / NO MAIN MERGE / NO FINALUSE**

## New original physical evidence (not an original-task result)

On **2026-10-16**, the GitHub Actions CPU runner actually downloaded the seven files from fixed `Qwen/Qwen3-0.6B` revision `16706fc57485378d4ffaf54139b29ccc66ae08fa`, validated its private regular-file manifest, loaded original pretrained weights, and completed **one public input** via `transformers==4.53.3` and the V25 shared loader. This is the first original-Qwen *pretrained* neural forward confirmed on this research line, separate from the V25 miniature **random-weight** constructor smoke.

- Historical exact source commit: `182ddd103bd6ec1ac1d82721ecd4876d5d5a1229`.
- Actual GitHub run: [38930227899](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/38930227899), job `117072021837`.
- Real pinned-model input: **67 tokens**; generated: **11 tokens**; measured original CPU generation time: **2.822091619 s**.
- Source logs exposed only cryptographic digests of prompt, input token IDs, output token IDs, answer text and immutable local model spec. The public source contains a question about France/Paris; **zero original LoCoMo private requests** were executed.
- The **generation step finished `success`**, but the **overall workflow finished `failure`** because the last source-scope safety guard read its own YAML and rejected its own `upload-artifact@` detection literal. The failure was not model-loading, model-generation, or original-Reader capability failure.

The public `V26_PUBLIC_QWEN_ORIGINAL_FORWARD_20261016.json` is a manually cross-checked **digest/count-only log extract**, not cryptographically signed independent model-host attestation. The V26 validator checks its exact observed fields, and must not be mistaken for a fresh inference or independent semantic grader. The original public answer itself and model weights remain excluded from source control.

## Fix

1. **Replace self-matching string inspection** with a structured safe-YAML examination of the entire staged Action, rejecting any unregistered job/step/action, write permission, upload action, private LoCoMo file access, altered model staging, or missing final check. The final check does not scan its own forbidden literal and does not weaken checks for actual file exfiltration.
2. **Explicit full attention mask** for the public Qwen probe and private 128-question reference generator: original model uses identical pad/EOS token IDs, so implicit mask inference is ambiguous. Every actual nonpadded input token now gets mask value 1. Frozen model revision, source text, input token ID sequence, greedy 24-token bound, and create-only physical journals stay unchanged.
3. Run static + adversarial regressions under both Python and `python -O`. Keep the V25 real miniature Qwen constructor qualification before acquiring pinned public model weights.
4. **CI does not inherit prior green:** only a subsequent exact-HEAD workflow that actually runs the fixed final safety step can be considered successful. The previous run remains `failure` despite observed successful pretrained generation.

## What has not happened

No original 128-case Qwen/LoCoMo reference result, human-adjudicated source sufficiency, independent citation entailment, heldout future evaluation, original model retention resolution, matched full lifecycle tokens/CPU/energy, NDU/System2 task lift, Split/Merge learner benefit, 10T/100T equivalence or production authorization. Changing attention masks must be treated as a declared inference-protocol improvement rather than pretending full operator parity already existed.
