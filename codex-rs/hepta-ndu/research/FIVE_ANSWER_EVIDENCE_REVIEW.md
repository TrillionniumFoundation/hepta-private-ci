# Frozen-answer review and content-interaction decomposition

Date: 2026-10-14. PR #1697. Parent dff55fe3c81781d436a093ca5d0e99789da8d85b.
This increment adds read-only analysis of an existing completed result. It is
not another training run, new independent data or a revised scoring threshold.
No prior training, raw answers, projection qualification, formal Reader gate,
main/CURRENT, model owner or production selection is changed.

## Why this step

The completed SELECT run38496209074 at1672d4b3 observed larger content interaction
for aligned8 than frozen/shuffled8 on all3 available comparisons. It also retained
zero exact-body/format matches and no independent semantic grades. Neither the
internal interaction nor exact string matching determines whether a paraphrase
is fully supported, partially supported, wrong or appropriately abstaining.

The next measurement therefore reuses the33 frozen successful answers and all36
planned slots. It requires no original model download, optimizer, generation or
teacher-forcing call. It does NOT issue its own independent human judgment.

## Exact input lineage

Only artifact11863981474 is accepted:
SHA256 aeb4113b6d2baace0a042f960876861c78b5449b6d9dac404dee2e5c041e46fa.
The existing extract_verified validates every archived member before extraction;
no archived source code is imported. Check the executed source, original plan,
raw/inventory seals, every arm raw seal, and exact public-input/answer joins.
Missing/failed slots retain their original denominator and cannot become answers.
Artifact membership validation is not an attestation of semantic truth.

## Distinguish the interaction's two components

The existing statistic is I=m_own-m_donor. For each saved candidate versus the
same frozen baseline report:

- change in own answer score and rival score under the original sources;
- change in their own-context margin;
- change in the donor-context margin;
- their difference, which exactly reconstructs the change in I;
- whether the candidate actually prefers the reference over the rival under
  its own sources, rather than merely improving a difference-in-differences.

All values are descriptive mean assistant-token log scores from existing saved
rows. A larger I can coexist with negative own-context margin. Length, topic,
weak donor annotations and source sufficiency remain unresolved. Do not declare
semantic accuracy, significance, independent transfer or candidate selection.
Missing comparisons remain unavailable, not imputed zero. Report task means
and equal-recipient-family means on the same scored subset. This decomposition
is explicitly post hoc; old registered results are not redefined.

## Two-pass review packet, no model or reference labels

First deliver only evidence-first/: unique questions and exact delivered source
texts, plus an unfilled sufficiency form. Reviewers judge source sufficiency
before seeing model answers, using sufficient/insufficient/uncertain and exact
source quotes. A session timestamp is not automatically an event date.

After the custodian receives and seals that pass, deliver answer-second/: raw
answer strings under opaque keyed random identities, questions and evidence,
with a form for answer/abstention/other, correctness and grounding separately.
No model arm, training budget, benchmark reference, donor annotation, condition
label, internal score or duplicate multiplicity is included. Empty evidence is
necessarily visible; this is not a claim of hiding the actual intervention.

Identical input+answer bytes require one quality review, with all original trial
multiplicities preserved only in custodian/. This is a review-cost optimization,
not extra independent observations. The source and answer bytes are never edited.
Random HMAC identities have no exported secret. The packet commits to the exact
custodian assignment list, preventing silent remapping of grades to model arms.
Different packaging runs intentionally have different masked IDs; reviews bind
the exact packet hash rather than just a filename.

The separate custodian/ artifact contains the model mapping, decomposition and
raw inspection view. DO NOT provide that artifact or original study to reviewers
who are meant to be blinded. Artifacts in one repository are not an access-control
barrier: a reviewer with other access can unblind themselves. Actual blindness,
independent identities, authorization and evidence-first timing require external
custody; a hash link or two different names does not prove them. Output templates
have NULL judgments, not default successes. No reviewer has been invented.

## Review import and honest denominators

The agreement subcommand requires two completed evidence/answer passes, distinct
reviewer IDs and separately provided full-review digests. Source quotes must
match actual delivered text at exact Python Unicode-character offsets; fabricated
quotes or source IDs are rejected. Quotes alone do not prove entailment.
Both passes must cover all unique items. No missing answer, invented reference,
incomplete review or stale evidence pass can be accepted as a complete grade.

Report categorical agreement and disagreements per original arm/condition. Never
choose the more favorable reviewer. Count agreed correct/supported answers only
where both reviewers also judged evidence sufficient; count agreed appropriate
abstention only on evidence both deemed insufficient. Keep uncertain, partial,
unsupported and all unavailable/failed original slots explicit. Do not silently
convert missing source references into incorrect answers or zero effects.

Even a fully populated agreement report has reviewer_independence_verified=false,
formal_reader_gate_issued=false and production_accepted=false. It is an input
for an externally authorized adjudication, NOT a replacement for the existing
independently pinned roster and dual-signed Reader gate. No automatic promotion.

## Execution commands

```sh
python scripts/memory_cell/answer_evidence_review.py prepare result.zip \
  --work /new/verified-select --output /new/review

# The independent custodian provides both review digest pins; this command does
# not obtain independence by hashing author-written judgments.
HEPTA_ANSWER_REVIEW_PIN_A=<externally-supplied-review-A-digest> \
HEPTA_ANSWER_REVIEW_PIN_B=<externally-supplied-review-B-digest> \
python scripts/memory_cell/answer_evidence_review.py agreement \
  --packet /new/review/answer-second/packet.json \
  --binding /new/review/custodian/assignment-map.json \
  --evidence-a /review-a/evidence-pass.json --answers-a /review-a/answer-pass.json \
  --evidence-b /review-b/evidence-pass.json --answers-b /review-b/answer-pass.json \
  --output /new/agreement.json
```

The dedicated workflow uses stdlib only, runs the new pure tests plus existing
source-projection/inventory tests, and reuses one1.5MB result archive. It does not
rerun model-training lanes. Evidence-first, answer-second and custodian outputs
are uploaded separately with hash inventories. No new source-model calls or
human grades are issued by the workflow. The helper's test grades are explicitly
fictional fixtures and never enter the real review package.

At source publication, local container/Python probes failed with ClientError;
new-source tests and completed packet extraction are NOT presumed. Report them
only after observing the exact pushed-source run. The completed predecessor387
unique-test result is not validation of this increment. Independent final-answer
quality, genuinely unseen families, trained Group/NDU benefits, real multimodal
split transfer and matched-quality shared-versus-replicated costs remain open.
