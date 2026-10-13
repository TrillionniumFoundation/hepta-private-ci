# Completed native execution; conditional Reader learning remains unproved

Date: 2026-10-13. PR #1697.
Exact tested implementation: `b3e0f4ee26d6fbe293ce65b9855e662529c038f2`.
Implementation tree: `34302dd35fcf60f6f5ff3de6352cb3f6e7f7818f`.
Hosted run **38424588299**, job **115390520316**, concluded **SUCCESS**.
The complete decoded job log and final job status were inspected. This result
record is documentation only and does not change the tested implementation.
No main merge, serving model switch, independent approval or task admission.

## 1. Same-source execution is now complete

All **236 tests passed, zero skipped**: 14 matrix/signature, 54 five-experiment
contract, 29 native Reader/Head, 61 Group, 28 response/readout, 33 saved-adapter/
counter/replay and 17 new Encoder snapshot tests. Python compilation, imports,
package checks and the original model/data artifact SHA verification passed.
This is the focused native workflow, NOT every repository/Rust/target-device
check or formal prospective-merge acceptance.

All its actual-model phases then completed successfully:

| Phase | Actual observations in this run |
| --- | --- |
| Official HF/PEFT response learning | 28 training examples and 56 measured optimization steps/decoder forwards per aligned and shuffled arm |
| Historical response comparison | 64 planned/successful rows: 48 real model calls plus 16 nonlearned always-refuse outputs |
| Saved-composition native replay | 4/4 calls, exact original answer/input-token/output-token equality; 32 extra decoder forwards |
| Original frozen Reader smoke | 16/16 calls, no failures; 731 decoder forwards |
| Original Encoder and Head smoke | 4 actual Encoder forwards; 32 Head optimization steps; Head parameters changed |

The previously blocked Encoder loading and Head optimization now execute under
the original immutable model inventory. The historical Head smoke uses supplied
category supervision and does not establish evidence-grounded answering,
shared-vs-replicated superiority or future task improvement.

The separate focused Encoder material audit **38424588230** was still queued
at the final observation used for this note. Its success is NOT inferred from
the native workflow. The actual native loading and training above are already
observed, not a forecast about that independent audit job.

## 2. The learned Reader result is still unconditional refusal

The response comparison uses only four historical questions from two held-out
source families, `locomo:conv-43` and `locomo:conv-47`. Each question is reused
across four conditions and four arms. Only three questions have available
benchmark reference answers. These are previously exposed public development
materials, not untouched confirmation and not independently reviewed semantic
sufficiency. Repeated arms/conditions/runs are not new independent questions.

Prescribed-refusal counts (each entry has four planned and successful rows):

| Condition | Frozen Reader | Aligned LoRA | Shuffled-positive LoRA | Always-refuse rule |
| --- | --- | --- | --- | --- |
| No evidence | 0/4 | 4/4 | 4/4 | 4/4 |
| Lexical retrieval | 0/4 | 4/4 | 4/4 | 4/4 |
| Annotated support plus distractors | 0/4 | 4/4 | 4/4 | 4/4 |
| Annotated support removed | 0/4 | 4/4 | 4/4 | 4/4 |

Both trained adapters refuse **16/16** inputs, including the annotated-support
condition. All arms have zero exact-body matches and zero syntactically valid
citations in the available diagnostic scores. Exact body/citation syntax are
not semantic answer judgments; a missing answer target is not a judged error.
No execution failure or unavailable oracle condition was filtered out.

Correct target pairing has not produced an observed advantage over the shuffled
control or unconditional refusal. Empty-input instruction following improved,
but there is no demonstrated evidence-conditional answering or overall Reader
adequacy. Neither candidate is selected or qualified. This is a bounded observed
collapse, not a general impossibility result about LoRA, shared Encoders or NDU.

The first actual result in run **38421445932** at `a87e56e6...` remains retained
in FIVE_READER_FIRST_TRAINED_RESULT.md. That earlier whole workflow failed at
Encoder loading after successful response/replay phases. The present run repairs
that execution failure and replicates the same learning outcome; it does not
replace or retroactively turn the earlier workflow green.

## 3. Model and measured-work identity

Each trained arm again used **230,400 trainable parameters**, **921,600 FP32
parameter bytes**, **1,843,680 optimizer tensor bytes**, **9,426 processed input
tokens**, **1,122 supervised tokens**, and **56 actual decoder forwards** for
56 optimization steps. Both save/reload checks passed and the base remained
unchanged. The adapter initialization and resulting tensor hashes match the
previous completed response study:

- Base tensor SHA256: `30aeed70fe072d8e93242d177384cbfa758d6d84ae0b2228314e1b72663e6915`.
- Initial adapter tensor SHA256: `66331d48169f0843740cc1b16db0f13b903c98a4a5c3d453cdd4d58202f9a844`.
- Aligned adapter tensor SHA256: `dc965c1618f812c53bef5de94b7af0c53a2c7e28cd9481630b656a2d4493fd87`.
- Shuffled adapter tensor SHA256: `75dd15dbbf2ab6d7229f921eb7e709ee2e6083faf818e6d68a60fb2f5b3ba8be`.

Matching tensor hashes and the same readout do not assert byte equality of all
run artifacts: raw records contain new measurements and saved metadata. No
cross-run full-raw equality proof is claimed. Within this run, all four native
composition replays exactly match their own sealed original answers and token
hashes. Reproducing refusals proves execution fidelity, not improved reasoning.

The response comparison recorded **843 inference decoder forwards**, separate
from **112 training forwards**, **32 replay forwards**, **731 frozen-smoke
forwards**, **4 Encoder forwards** and source-test/fixture work. Both fitting
arms and repeated staging/loading are paid. Do not use one region as the total
cost of this workflow or entire research increment. Energy, FLOPs and process
peak values remain unknown; start/end RSS is not peak RSS. Equal steps/tokens
are not a matched-compute or TCO claim.

The loaded composed Reader has **134,745,408 parameters** including the LoRA,
not a 421M Laya baseline. Same-composition Cells share one fixed owner; distinct
adapters still pay for distinct loaded model objects. No active model or CURRENT
was changed by fitting or replay.

## 4. Why the Encoder repair is verification rather than an exemption

The actual original-material audit **38423208299** found 104 saved tensors and
103 state_dict tensors with all 103 state tensors exactly matching. The sole
extra key was `embeddings.position_ids`, int64[1,512], exactly equal to the
loaded nonpersistent BERT buffer and configured zero-based positions.

The patch verifies that one exact stock-BertModel/key pair against the loaded
buffer AND canonical arange with the required dtype, shape and persistence.
It does not discard unknown keys, rename namespaces, replace model bytes or
omit learned heads. All original snapshot and parameter checks remain, with
17 added positive and adversarial snapshot tests now actually passing in the
236-test run. See FIVE_ENCODER_BUFFER_VERIFICATION.md for the diagnosis and
restricted acceptance rule. The actual original pretrained Encoder subsequently
completed its four forward calls and the existing Head optimizer ran.

## 5. Sealed evidence and limits

Current response plan SHA256:
`c6a32fa6e823327f057b87da376b25d32b976e399a9e82eb0fba8854ed1771ad`.
Current response raw SHA256:
`71cbb9ce9e78b3209316c22b51936d3036b57a6d22ceeb989065fbc53e4a2309`.
Current replay raw SHA256:
`ed1425f9a0944912ca10f89cfd30ca6c27eeeaee704a3710e1002dee978c210a`.
Current original-smoke raw SHA256:
`e989be9cf5740917390f13289ce8d73aeb655e7e53c1fe57409ce3942b06f0be`.

Artifact **11829020399**, GitHub-reported **1,969,909 bytes / 84 files**,
ZIP SHA256 `8263c249c630ee30d1aaf9f7c7b2defeb488157092770cebc06e95ee53f8752e`.
It retains generating source, test logs, original outputs, training/replay
journals and checkpoint evidence, excluding original pretrained model material.
No local rehash or local execution is claimed: working container/Python access
returned infrastructure ClientError during this increment.

The five requested independent causal experiments remain incomplete. The next
scientific decision is whether a separately registered development objective
can preserve supported answering while distinguishing absent evidence. It must
be diagnosed on training and a distinct validation split, not chosen using
these four now-exposed evaluation outcomes. Group/NDU learning, true multimodal
and split transfer, independent future families, full resource comparisons and
native production ownership remain separate work. No gate is opened by this
successful execution receipt.
