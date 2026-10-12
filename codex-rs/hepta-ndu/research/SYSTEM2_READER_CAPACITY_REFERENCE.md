# Frozen 135M Reader capacity versus a pinned independent 0.5B reference

Scope: **research-only under PR #1546**. This protocol does not replace the
production Reader, Encoder, NDU/FBSDE solver, controller, or search code.

## Why this is the next decisive control

The original model inventory identifies the frozen production-independent
research reader as `HuggingFaceTB/SmolLM2-135M-Instruct`, exact revision
`12fd25f77366fa6b3b4b768ec3050bf629380bac`. On the original 20
previously exposed synthetic one-hop tasks, complete controlled experiments
showed no adequate answer/refusal output: adding a competing Token fact
usually induced `E1/E2` echoes, removing source labels instead induced JSON
echoes, and none of the 140 answer-only trials yielded a strictly correct
answer or a correct prescribed refusal. These negative results were measured
on real hosted model calls and are not NDU learning outcomes.

The useful question is now whether these tasks/prompt instructions are
answerable by **another fixed Reader**, rather than presuming bigger search,
more Cell parameters or longer FBSDE recursion will make the 135M Reader
adequate. A separate public, instruction-tuned reference model is pinned:

- Model: `Qwen/Qwen2.5-0.5B-Instruct`
- Exact source revision: `a338b55dd21219a5f4da42bc11a9313d1a27d4cc`
- Source and license: https://huggingface.co/Qwen/Qwen2.5-0.5B-Instruct
- The earlier pin `367ae90eaf97b8d64787d6ee9101a04460b55392`
  **deleted `config.json`** upstream; hosted run 38287169597 failed closed
  at model staging without any capacity-model inference. The replacement
  `a338b55dd21219a5f4da42bc11a9313d1a27d4cc` is a distinct
  complete upstream snapshot with config, tokenizer and safetensors.
  Re-pinning is an explicit model-source change, NOT successful inference or
  identical pretrained parameters automatically assumed.
- Snapshot includes only model safetensors and ordinary tokenizer/config
  files, pinned by revision and independently hashed in the hosted receipt.
  No remote custom Python code is trusted, and model is frozen at inference.

**This is deliberately NOT compute matched.** Parameters, source pretraining,
tokenizer, text-token counts, wall time, inference CPU and architecture all
differ. The only supported interpretation of a relative improvement is
**Reader capacity / model-choice headroom** on these synthetically generated
questions. It is NOT an NDU, shared Encoder, retrieval or training gain.

## Fixed inputs and negative controls

Reuse and reverify the entire external 140-response answer-only archive
(artifact `11760345185`, SHA256
`a278014bae564336fc4d63335154cadbf14febc73620d958f45648b17ca0622a`)
and its original immutable cardinality predecessor (artifact `11756357532`,
SHA256 `9f4a4ed9429212b98befffca27a297780d61317eaed8be519b1cb6880037f121`).
Both were generated with externally pinned model/source identities. The
completed label archive's 140 raw answer seal is
`6f630a86d374658049377d4611f92fd6c0dd6626c267eef7c37d77f07f5aeaa2`.
All original source excerpt bytes, question identity, source selection, Reader
profile, token digests and scores must pass the existing read-only
`system2_onehop_label_pair_audit` replay **before new model inference**.

Two fixed sets, registered before the new reference model is called:

1. `exposed_20`: the same 20 previous single-hop questions, with 80 historical
   135M answer-only conditions available for direct comparison.
2. `fixed_new_20`: catalogue generator indices 20:40, with new question/source
   identities disjoint from `exposed_20`. These tasks are new to **this**
   capacity control but share the same synthetic grammar and can share
   intermediate linguistic features. They are NOT independent natural language
   data or human-verified semantic tasks.

On each 20-question group, four evidence conditions:

| Arm | Evidence | Proper output target |
| --- | --- | --- |
| `single_fact` | One directly relevant fact | Answer-only correct Token |
| `target_decoy_two_first` | Direct fact + one competing Token fact | Answer-only correct Token |
| `decoy_one` | One irrelevant Token fact | Exact prescribed refusal |
| `no_evidence` | Zero evidence | Exact prescribed refusal |

Total **160 new reference model attempts**, with 80 older 135M outcomes reused
verbatim, not re-executed. The **text** of the instruction and complete JSON
prompt, selected original evidence bytes and greedy `max_new_tokens=64` setting
are shared. The token IDs/chat template, token counts and actual CPU differ;
these differences are retained, not claimed equal.

## Nonleaking admission and scoring

Source choice reads only question and source bytes, not the expected answer.
The new reference Reader receives no target labels. After saving and `fsync`
of each attempt, all raw Reader outputs are SHA256 sealed **before scoring**.
All completions, failures and planned denominators remain explicit. For
sufficient conditions the only accepted answer is the single exact target
Token. Under insufficient evidence the only accepted answer is precisely
`I do not have enough evidence.` Token mentions, evidence-label echo and
unsupported Token copies are recorded separately; no programmatic
postprocessing can be scored as a new model answer.

Predeclared capacity admission is at least **15/20 exact answer-only replies**
in EACH positive arm and at least **18/20 correct refusals** in EACH negative
arm, on BOTH the exposed and fixed-new groups. Passing merits independent
natural-language/human confirmation only, NOT production activation. A
failure means this tested larger Reader and prompt did not establish the
necessary baseline; it does not prove every possible Reader must fail.

## Validation and explicit nonclaims

Local dependency-source slice: nine scoped tests including a successful
fully pinned baseline ZIP audit and a fake Reader end-to-end 8-cell runner,
with injected malformed evidence, missing rows, forged outputs and model
exceptions. Full pinned Torch 2.5.1 tests, Ruff and all MemoryCell regressions
are performed by the new isolated GitHub Actions workflow. The hosted workflow
also captures complete environment, real token/Cpu accounting, model inventory
hashes, exact source SHA and raw Reader results. No model weights are uploaded
back to artifacts, and no new model training occurs.

Even a successful 0.5B capacity control cannot establish citation semantics,
NDU/FBSDE reasoning emergence, calibrated continuation probabilities, strong
Reader performance on natural documents, or compute-matched superiority.
