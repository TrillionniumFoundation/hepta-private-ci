# Fixed question/evidence relevance training after answer inspection

Date: 2026-10-14. PR #1697. Parent: 58583e9c4420415b4b87a5ef119a7705f4655319.
This is new weak-supervision DEVELOPMENT, not an independent sufficiency judgment,
Reader admission, main/CURRENT update, or retrospective change to old results.

## Motivation and fixed manipulation

The completed answer review preparation (a5677489 / run38510513152) preserves
useful aligned8 answers, a pets-as-family regression, and irrelevant nonempty
contexts that induce copied but question-irrelevant answers. No external semantic
reviews were received. This increment does not manufacture them or fill forms.

Original answer/empty training pairs remain byte-for-byte unchanged. The new
optional relevance_profile enters the existing fit_response_adapter lifecycle,
not a second optimizer or copied trainer. For each eligible original TRAIN
question q, select a donor question q_d and its sources D with the UNCHANGED
reader_content_swap identity rule: same TRAIN partition, another family, equal
source count, distinct normalized answer and source body. Keep every original
pair, including those with no donor. No SELECT/TEST target supplies training.

The added comparison uses (q_d,D) and (q,D). D has identical nonempty bytes,
positions, local citation names and dates in both. Questions genuinely differ;
options stay identical. Score the donor's complete annotated answer plus its
current S1/S2 citations and the prescribed refusal under each context. The
aligned weak target prefers the donor answer for q_d, refusal for q. Finding a
phrase in D or detecting nonemptiness alone cannot satisfy opposite preferences.
The same target suffix is used on both sides; original answer content, including
brackets and dates, is never repaired or stripped by a regex.

Cross-family swaps are WEAK negatives, not a proof that D is insufficient for q.
Shared topics, multiple acceptable answers or annotation errors can violate this
assumption. Surface entity/question cues may solve some pairs. Thus success does
not alone establish semantic relevance, calibrated abstention or reasoning.
Independent evidence-first review and fresh task families remain necessary.

## Four fixed arms, three fresh fits

1. Frozen Reader: no optimization.
2. repeat-empty: original paired margin plus the donor-answer context and an
   EMPTY recipient-question context. Controls repeated answer/refusal supervision.
3. nonempty-aligned: same original units, targets, update grouping and donor
   identities; the negative recipient context now contains D.
4. nonempty-reversed: identical nonempty inputs and target multiset to aligned;
   reverse ONLY the supplementary answer/refusal preferences. Original supervised
   pairs remain correct. This is an intentionally wrong-direction control.

All fresh fits start from the same original base/LoRA seed. Fixed rank4/alpha8
q/v adapters, original learning rate, eight epochs; no validation stopping,
intermediate checkpoint choice, budget search or larger model. Full-logits-v1
is mandatory. Failed assistant-only weight equivalence remains failed at its
original tolerances. Old trainer calls with relevance_profile=None retain their
original metadata, schedule, losses and counts.

Reuse original paired backward, then accumulate supplementary paired losses
before ONE optimizer step, clipping, save and exact own-adapter reload. Original
loss has weight1 and extra paired loss weight1; both controls use the same weights.
At most two response graphs are held at once. Each available extra pair costs
FOUR additional actual decoder calls; a donor-unavailable original costs only its
original four. This is not dummy work or a match in total tokens, FLOPs or energy.
Measured dispatches, token counts, loss diagnostics and partial failures remain.

## Material and execution boundaries

The local programmatic material precheck verified the original 376,363,859-byte
archive SHA07b357cbb3362f4afa4dc1872ab7e28e8a46daaf338f2636fed8d40fbcee76af,
extracted the exact benchmark bytes by their prior pin, and reconstructed the
28 previously admitted dated TRAIN rows. Their complete canonical digest equals
the saved budget study. Fourteen original pairs remain; thirteen have eligible
supplementary donors. The remaining pair is NOT removed or supplied a fake
negative. Planned eight-epoch execution is112 updates per fit; with this inventory,
864 actual decoder calls per fit are expected and MUST be measured, not prefilled.
Local official tokenizer preflight and pretrained execution were not performed.

Before loading a Reader, compile every original unit and every supplementary
context/target for all three profiles under unchanged token limits. A too-long
chosen donor fails the study; no shorter donor or altered recipient is searched.
Seal train plan, compilation census and all free-generation requests first.
All three fits must share the same initial adapter hash and example plan.

Free-generation TRAIN recipients remain the old four. Each has own sources,
empty input, donor sources with the recipient question, and the matched donor
question. Reused donor identities remain dependent observations, not new tasks.
SELECT requests are exactly the sealed public cases from run38496209074/artifact
11863981474 (ZIP SHA aeb4113b6d2baace0a042f960876861c78b5449b6d9dac404dee2e5c041e46fa).
Keep its missing reference/donor slots and original four-score content contrasts.
No new inventory selection is made from model outputs.

Free outputs seal per arm BEFORE any target-based readout. Report original exact
body/citation diagnostics separately from refusal behavior and weak likelihood
preferences. The intended orientation is used to diagnose ALL models, including
the reversed-control model; it is not graded against its deliberately wrong
training direction. SELECT remains already-exposed DEVELOPMENT, not confirmation.
Raw answers are not rewritten and no formal semantic score is generated.

## Validation at initial publication

22 distinct local pure tests passed (16 pairing/manipulation +6 generation-plan),
zero skips. Python compilation and workflow YAML parsing passed. The prior trainer
blob9be500fc4372fd1cff3bd2e271e3d76ac066c5d2 was checked against the repository
before patching. This is a reconstructed source slice, not a complete checkout.
Seven new official tiny-HF/PEFT regression definitions are submitted, not locally
claimed passing: three-profile optimization/reload, summed gradients/eight calls,
unavailable-pair preservation, profile rejection, tokens, collapsed input checks,
and partial-failure accounting. Local HF/PEFT dependencies are absent.

The dedicated workflow requires these and all inherited suites before retrieving
pinned material and running actual pretrained fits. A new push modifying the
existing trainer may ALSO trigger inherited native regressions; that duplicated
work is not free. Logs, actual source, raw results, saved candidates and failures
are retained without exporting original pretrained weights or the full dataset.
No future job success, quality improvement or resource benefit is asserted here.

No external reviewers, approvals or independent grades are generated. No existing
22-arm/15-contrast/768-configuration plans, production owner, review roster,
Group/NDU implementation or scientific threshold changes. Five formal experiments
remain open; this is a concrete attempt to repair the observed nonempty-relevance
failure, alongside (not in place of) independent review.
