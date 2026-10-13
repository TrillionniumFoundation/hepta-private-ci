# Evidence-paired development after the observed refusal collapse

Date: 2026-10-14. PR #1697. Parent 9973326e3629b3ac2fd0d422776b6d757f9374d8.
The original 236-test execution and unconditional-refusal result remain intact.
No production selection, independent approval or five-experiment completion.
At publication these new sources/tests are submitted; actual execution must be
reported separately at its exact commit. Local container/Python returned
ClientError; no local pass is asserted.

## Question and fixed controls

The next question is whether the model can learn different answer preferences
for the SAME question when annotated supporting evidence is supplied versus
when all evidence is absent, without collapsing to a constant refusal.

Six arms are fixed before new outcomes: frozen Reader; original saved aligned
adapter; paired response CE; paired response CE plus conditional margin; the
same margin objective with cyclically permuted positive responses; always-refuse.
The old adapter is reloaded via the existing strict composition owner. No new
base model, decoding prompt, vocabulary, generation algorithm or larger LoRA.
Rank4/alpha8 q_proj/v_proj and original learning rate, two epochs and seed remain.
The inherited default response-ce-v1 single-example schedule and arithmetic stay.
The two new loss names are explicit; their configuration is sealed in training
plans, journals and receipts. PROFILE still names the SAME response-LoRA format;
new adapter/receipt hashes produce distinct composite Reader identities.

## Objective and why it addresses a specific shortcut

Let l(y|q,E) be mean log probability of assistant-response tokens, including EOS,
under teacher forcing. Prompt tokens are masked; causal logits are shifted once.
These are length-normalized sequence scores, NOT calibrated answer probabilities.
For answer a, prescribed refusal r, support E and empty evidence 0:

m_E = l(a|q,E) - l(r|q,E)
m_0 = l(r|q,0) - l(a|q,0)
L_CE = -[l(a|q,E) + l(r|q,0)]/2
L_margin = L_CE + [softplus(1-m_E) + softplus(1-m_0)]/2.

If the score preference ignores evidence entirely, m_E + m_0 = 0, so both
margins cannot be positive. This is a property of the stated score objective,
not proof that optimization succeeds or generalizes. A mere evidence-presence
shortcut can still satisfy these pairs. Nonempty distractor and support-plus-
distractor validation inputs remain essential. No semantic insufficiency label
is fabricated for distractor-only input; references are benchmark annotations.

Both contexts accumulate gradients before one optimizer step. Paired CE is the
schedule control; comparing only with the old single-example CE would confound
the objective and update grouping. Each pair runs four observed likelihood
forwards. CE evaluates countertargets under no_grad for diagnosis; margin also
backpropagates them. There is NO dummy backward to claim equal compute. At most
two sequence graphs are retained at once. Actual costs and scored tokens are
separate from positively supervised tokens; same forward count does not mean
same backward work, energy or end-to-end cost. No compute-matched superiority.

## Train versus validation, never test-driven tuning

Use the existing source-family partition: four identity-selected questions per
TRAIN family, two per SELECT family. Original TEST families, including the four
previously reported questions, are excluded from this new study. The existing
historical response replication still runs separately as a regression and must
not be mistaken for this new train/select study. The public benchmark itself
is already exposed, so SELECT is development validation, not unseen confirmation.
No replacement of ineligible questions and no seed/epoch/checkpoint search.

Training uses the original admitted answer/empty-refusal pairs. Validation
teacher-forcing examples keep split=select and are rejected by the optimizer.
Public generation keeps every identity-selected validation question even if
its target or support annotation is unavailable. No support cap is silently
truncated. Pair compilation checks exact common context prefixes, equal response
token suffixes across contexts, and genuinely different neural inputs.

For free-generation diagnostics, use four fixed admitted TRAIN pairs under
support-only and no-evidence conditions; all selected validation questions use
support-only, empty, support-plus-distractors and support-removed conditions.
The original registered-citation-only exact-body readout remains unchanged.
Source identifiers, bracketed answer content and raw model outputs are retained.
Targets never enter generate_exact. Each arm's raw generation file seals before
teacher forcing or target-based readout. Frozen post-training likelihoods are
measured for ALL admitted training pairs plus eligible SELECT pairs, recording
separate conditional margins and their interaction. Training success must not
be substituted for validation success; likelihood improvement must not replace
greedy answer/grounding quality. All candidates remain unadopted.

## Existing lifecycle and measurements

The new objective is integrated into fit_response_adapter rather than a second
trainer/loader. Original immutable-base checks, optimizer journal, exact saved
adapter reload, external admission and current serving models remain unchanged.
The driver reuses already verified original/clean material beneath the previous
study's staging directory, avoiding another model download or weight copy.
Additional decoding, teacher forcing and training are all separately charged.
Host interruption leaves started records; Python exceptions retain failure rows
and exit nonzero. No automatic retry. Unknown device energy/FLOPs remain null.
The script is not a hostile-code sandbox or a production FinalUse service.

The native workflow retains all inherited tests and model phases, adds the new
pair suite, then runs the new study using the existing staged material and the
actual saved original adapter. Artifacts retain source, outputs, diagnostics,
optimizer journals and adapters, but exclude original pretrained weights.
This is not a parameter-grid expansion or a substitute for the five experiments.

Primary implementation references checked for scoring and adapter lifecycle:
https://raw.githubusercontent.com/huggingface/transformers/v4.57.1/src/transformers/loss/loss_utils.py
https://huggingface.co/docs/peft/v0.17.0/package_reference/peft_model
