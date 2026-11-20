# A-only diagnosis of repeated faulty-source responses

## Finding

The inspected implementation and actual A artifacts do **not** support a concrete masking, input/output boundary, target construction, output extraction, normalization, or truncation defect. The direct observation is that the frozen student policies often continue the faulty solution despite being trained on correct complete-function targets. Why this happens is not causally identified by this four-record experiment.

The diagnosis uses only the original A training material, original training steps, A outputs, and executed source. It does not use future-task answers to choose a fix or training configuration. No additional model forward, generation, optimizer step, or native child ran. No new training candidate was selected.

## Exact tokenizer and loss-boundary checks

The existing frozen tokenizer was loaded offline; the model weights were not loaded and CUDA was not initialized. The tokenizer/config/merge/vocabulary hashes are recorded in [A_STATIC_DIAGNOSIS.json](A_STATIC_DIAGNOSIS.json). The exact execution command and durable owner receipt are in [POSTEVALUATION_CONTROLLER_RECEIPTS.json](POSTEVALUATION_CONTROLLER_RECEIPTS.json).

| A project | Native prefix tokens | Native complete input | Target incl. terminator | Head chunks | Document complete input |
| --- | ---: | ---: | ---: | ---: | ---: |
| python-attrs/attrs | 791 | 916 | 125 | 1 | 912 |
| Textualize/rich | 2,025 | 2,779 | 754 | 3 | 2,776 |
| tox-dev/platformdirs | 2,282 | 2,618 | 336 | 2 | 2,614 |
| python-humanize/humanize | 2,129 | 2,196 | 67 | 1 | 2,193 |

All inputs fit the frozen 3,584-position training shape. Every failed action, feedback, and other prefix label is -100. The selected-position chunking covers each target position exactly once. The source's causal shift predicts labels at position t+1 from hidden state t; per-chunk loss weighting uses the original total supervised count. The target IDs are identical between arms.

Each target decodes to the exact complete maintainer repair plus the tokenizer's native EOS/newline terminator. Pure codec reconstruction produces the exact original maintainer AFTER bytes, whose actual original native reference receipts were already retained. This is not supervision on the failed BEFORE action.

For all four native examples, the **entire training-prefix token sequence equals the actual common-P-prefix inference input**. The document arm deliberately merges observations into a user document and therefore has different prefix IDs; this is the declared layout treatment, not an accidental token-boundary mismatch.

## Actual A output and admission checks

For every one of the 24 actual A generations, re-rendering/re-tokenizing the complete messages reproduces the retained input length and digest. Decoding the retained generated token IDs reproduces the exact raw answer.

All 24 outputs contain EOS, and none hits the 2,048-token output limit. There is no observed truncation removing the repair. The generation code slices after the input-token prefix and does not substitute a maintainer answer or replace the student's function.

Pure codec/admission replay reproduces all 20 executed native payloads byte-for-byte and preserves all four original admission rejects. The two document own-prefix platformdirs attempts contain content outside the permitted function/constant. The two native own-prefix rich attempts change the permitted signature/decorators. The latter reason is nested inside the original verification receipt; the complete call ledger records it explicitly.

These results rule out the inspected mechanical explanations for this run. They do not prove every aspect of the training implementation correct under all other inputs.

## What the actual retained optimization shows

The existing rank-4 q_proj/v_proj adapters use alpha 8 and learning rate 0.0001. Each arm completed the original 32 optimizer updates: eight visits to each of four records, 56 actual outer forward/backward pairs, 10,256 supervised positions, and 200,704 padded positions. Original parameter digests changed, gradients are finite/nonzero, and these steps were not rerun.

[A_EXISTING_TRAINING_LOSS_READBACK.json](A_EXISTING_TRAINING_LOSS_READBACK.json) is derived from the two unmodified original STEPS.jsonl files included here. First-to-last teacher-forced mean losses are:

| Project | Native loss, first to eighth visit | Document loss, first to eighth visit |
| --- | ---: | ---: |
| attrs | 0.214287 → 0.063085 | 0.214350 → 0.068038 |
| rich | 0.803091 → 0.708249 | 0.799516 → 0.705051 |
| platformdirs | 0.453139 → 0.303860 | 0.426402 → 0.291660 |
| humanize | 0.156627 → 0.017082 | 0.112229 → 0.014736 |

There is no observed optimizer stall. The longer rich repair remains poorly fit even under teacher forcing. A lower mean next-token loss does not guarantee that greedy decoding chooses the first changed token and remains on a corrected trajectory.

The actual repairs vary: attrs adds handling of __forward_arg__; humanize replaces the branch sequence with return abs(delta); rich changes substantial control flow and documentation; platformdirs adds a carriage-return constant and line-handling behavior. They are not equivalent optimization problems.

A mechanical target-versus-failed-action token alignment gives equal-target fractions of approximately 88.6%, 54.4%, 44.9%, and 96.9% respectively. These are SequenceMatcher alignment counts, **not a semantic classification of repair-bearing tokens**. They cannot establish that copying dominates every target or prove a causal dilution mechanism. In particular, rich and platformdirs have substantial changed content.

## Supported interpretation and remaining uncertainty

The protocol supervises four fixed parent first-failure contexts. It does not collect corrective labels for the student's own newly visited states during training. Limited state coverage, limited optimization, and the gap between teacher-forced token loss and free autoregressive repair are plausible contributors.

That interpretation remains a hypothesis. Common-P inference itself repairs only humanize, so self-rollout distribution shift alone cannot explain the failures. A-only results also do not prove that increasing rank, extending optimization, changing loss weights, or changing the output representation would help.

No implementation patch is justified by the specific faults inspected here. No target was changed, no admission rule was relaxed, no new training took place, and no future answer was used for tuning. A future experiment must separately predeclare a hypothesis, treatment, fixed budget, stopping rule, and genuinely unexposed confirmation material.

