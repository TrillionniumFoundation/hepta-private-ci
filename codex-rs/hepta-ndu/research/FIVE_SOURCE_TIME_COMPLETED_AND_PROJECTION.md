# Source-date result and exact assistant projection qualification

Date: 2026-10-14. PR #1697. Parent: 00104aaf8eff351359a779ccc034cbbe6e4aa023.
No main/CURRENT/serving change or independent Reader approval.

## Completed source-date comparison, not inferred from a green test job

Source 244c8b5a9c1cd574bcbfb16441b6b143b59e8374, run 38433638352, job
115421927360 completed SUCCESS. Artifact 11833328492 is 2,012,556 bytes;
SHA256 8ee80dfe247b70d8b0329727a7e80078f056d8e810126b5051aae7f670c33f7d.
This turn verified the downloaded ZIP, all 72 listed member hashes (73 files
including SHA256SUMS), tested-source identity, aggregate raw and four arm seals.
There are 287 passing test invocations, 284 distinct identities, zero skips;
three imported NativeAdapterTests repeat. The 25 source-date tests actually pass.
These are focused Python checks, not full repository/native-platform acceptance.

All 96 generation rows succeeded. Four TRAIN questions and four SELECT questions
are reused across arms; these are not 96 independent tasks. Teacher forcing uses
14 TRAIN and 3 eligible SELECT pairs, with the fourth SELECT reference missing.
TEST families remain excluded. All four arms have zero prescribed refusals,
zero registered exact bodies and zero citation-syntax counts. These diagnostics
are not independent semantic accuracy. Raw paraphrases have not been re-scored or
silently edited. Both desired likelihood preferences remain positive on 0/14
TRAIN and 0/3 SELECT pairs in every arm.

| Arm | TRAIN supported margin | SELECT supported margin |
| --- | ---: | ---: |
| Content frozen | -0.915926 | -0.861943 |
| Date frozen | -1.105182 | -1.030147 |
| Content paired margin | -0.785026 | -0.720043 |
| Date paired margin | -0.886007 | -0.778073 |

These are mean response-token answer-minus-refusal log scores, not probabilities.
Restoring actual source dates preserved needed input information but did not
solve the observed conditional preference criterion or establish answer gains.
This is not proof that source dates are useless, nor a general impossibility.
No original target, input profile, training run or negative result is replaced.

The run paid 3,267 generation decoder forwards, 272 teacher-forcing forwards,
and 224 training forwards for 56 total optimizer updates. Two fitting arms kept
230,400 trainable parameters and verified immutable bases/saved reloads. Date
fitting processed 22,132 input tokens versus 18,852 content-only tokens; both
scored 2,244 response tokens. Costs of staging, tests and earlier runs are extra.
Raw SHA256: 74fd5cfe7104b2c967ee077c0acac16027f4caeba838f69a4b3824059109f6d1.

The 2-versus-8-epoch study 38437516618 was still queued at initial inspection in
this increment. Its result is not inferred or cancelled. No new learning target,
weight size or optimization budget is selected from the date outcomes.

## New implementation: do not project vocabulary scores that the loss discards

Existing paired sequence_score runs the complete decoder and LM head on every
input position, although only assistant suffix tokens enter the loss. The
opt-in assistant-logits-v1 uses the pinned official Llama logits_to_keep tensor
API to select positions [prefix_length-1, ..., sequence_length-2] BEFORE the LM
head. Complete input tokens, attention, hidden states, causal dependencies and
context gradients are retained. First answer token and EOS are included; no
second shift, vocabulary pruning, context detachment, hidden-state cache or
approximate probability replaces the existing objective.

Full-logits-v1 remains the default. Original response-CE profile is unchanged;
the optimization is explicitly paired-only, entered by projection_profile.
Old default objective metadata stays unchanged; opt-in plans/journals/receipts
bind vocabulary_projection=assistant-logits-v1. Original save/reload, base checks,
counts, optimizer, schedule and candidate-only ownership remain. No model is
silently retried using another backend. Wrong shapes or unsupported model
classes/attention/checkpointing fail. Prompt-position vocabulary logits are not
computed or inspected for finiteness; selected logits and loaded weights still
undergo checks. The complete decoder remains untruncated.

The same mathematical scalar loss and gradient can have small floating-point
GEMM differences. Registered tests compare losses and all trainable gradients,
not only output shapes; pretrained qualification compares the complete per-step
loss trajectory and saved adapters within explicit tolerances. No bitwise or
universal backend equivalence is asserted.

## Verification and actual-work qualification

15 pure Torch fixture tests passed locally, zero skips, including all-parameter
and prefix-token gradients, four AdamW updates, first/last target handling,
ignored-selection rejection, and observed vocabulary-output byte counts.
Compilation passed. They do not use a pretrained Reader or prove task learning.
Five additional required official HF/PEFT fixture definitions cover both paired
objectives, nonzero LoRA gradients, original trainer saved reload and counters,
and fail-closed profile/model dispatch. HF/PEFT were unavailable locally, so
those are submitted definitions, NOT local passes.

A dedicated exact-source lane retains inherited contracts and runs the two
fresh one-epoch candidates on ALL previously admitted, dated TRAIN pairs. It
uses the existing immutable original archive, official model and trainer; it
never reads SELECT/TEST target outcomes or substitutes synthetic weights.
Compare same initialization, target tokens, order, update/decoder counts,
per-step losses and saved LoRA tensors. Each candidate reloads its OWN exact
saved bytes. All extra fitting and profiling cost is recorded.

LM-head hooks count actual projected positions and produced tensor bytes. The
largest returned logit tensor is NOT process peak memory, total activations,
energy or whole-model FLOPs. The decoder still does all original context work;
no cross-Cell inference sharing or end-to-end speedup follows automatically.
Existing workflows are not cancelled; any inherited refitting remains paid.

Primary code checked:
https://raw.githubusercontent.com/huggingface/transformers/v4.57.1/src/transformers/models/llama/modeling_llama.py
https://raw.githubusercontent.com/huggingface/peft/v0.17.1/src/peft/peft_model.py

Independent adequate Reader, trained Group/NDU benefits, true multimodal/split
transfer, untouched families and matched-quality shared/replicated lifecycle
comparisons remain open. This efficiency qualification does not open those gates.
