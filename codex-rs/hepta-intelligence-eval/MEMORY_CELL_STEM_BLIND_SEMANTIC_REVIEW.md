# MemoryCell: strict-native 32-question blind semantic review handoff

**Status: worklist only; no independent reviews, production qualification or
semantic-citation precision.**

## Frozen evidence and identity

The exact source-pinned strict-as-of native Matrix source is
`cb9e98365b5f46e00fb2693f548a7215b1ed1145` (tree
`022c9aa8abc095c91ef744644329aaed12564859`), original private GitHub
artifact `11702192907`, ZIP SHA-256
`be3393f448993451c7860e8867e28a79f5fb7f95d5773f79ed55b30d12a84776`.
The exporter validates the full immutable ZIP manifest, its generating commit
and tree. It only reads the original pre-registration, raw 576 policy attempts
and 32 raw zero-evidence controls. **It never opens benchmark gold answers,
posthoc source-correctness labels, privileged answer-literal Oracle outputs or
model weights.** Nothing is generated or trained.

Review scope is the **32 distinct registered select / retention / test /
transfer questions**, with exactly two conditions per question: the original
checkpoint-48 frozen-ranker's fixed Reader answer and an isolated same-model,
same-prompt Reader answer with no supplied evidence. Every case has a stable
opaque ID and a deterministic A/B slot order. Reviewer-visible questions
include verbatim question text/time, original raw response and actually
delivered excerpt(s) only; model-arm names, source family labels, native
support scores, original question IDs, and any standard answer are excluded.
Visibility of an evidence excerpt is inherent and cannot be blinded: this is
**arm-/target-blind**, not double-blind evidence-presence masking.

The separate **owner-only mapping** binds original question IDs, phase and
source family to slot A/B, original canonical Reader request, exact evidence
bytes and original answer digests. The workflow now emits **two distinct
private Actions artifacts**, each retained for seven days: one contains only
`blind-question-answer-worklist.jsonl`, the unsigned return template and
their SHA-256 manifest; the other contains
`private-owner-case-mapping.json`, original archive pins and audit source.
**No owner mapping is included in the reviewer-facing archive.**
GitHub repository artifact access is still shared by the same repository
readers; this is workflow-level accidental-disclosure separation, not a
separate reviewer-access control. The data owner must authorize reviewers,
send only the reviewer-facing archive and keep the owner mapping private.

Reviewers must treat source excerpts, question text and model answers as
**untrusted data**, not operational instructions. The reviewer-visible
artifact is for authorized independent evaluation only, not a public release.

## Evaluation rubric to be filled by genuinely independent reviewers

Each of the 64 condition slots has fields left `null`, including:

* `evidence_sufficient_for_question`: can a competent Reader answer the
  question from only the delivered source text, without an outside memory?
* `answer_claims_supported_by_evidence`: are the actual generated factual
  claims supported by that text, not merely semantically related?
* `cited_spans_entailed`: do all explicitly cited source markers entail the
  attached assertions? Empty citation sets are **not 100% precision**.
* `missing_provenance_or_unreviewable`: genuine missing, ambiguous, withdrawn
  or temporally non-admissible source; failure to answer; or inadequate context.

Raw answers and excerpt bytes may include sensitive native conversation text.
Reviewers must not receive model training logs, native gold labels, Oracle
literal-answer spans or the private owner mapping until their judgments and
identity-attested returns are frozen. Apply two genuinely independent
reviewers when possible, record each verdict and conflicts, and escalate
disagreements to the evidence owner without changing the original answers.

The exporter **does not** verify reviewer credentials, generate or sign
attestations, or import any self-issued review into production acceptance.
All verdicts are deliberately null and no semantic precision is computed.
An external owner must verify review identity, authorization, immutable input
hash and signature, publish a complete denominator, and preserve dissent and
unreviewable rows. The worklist alone cannot establish sufficient evidence,
learning gains or a valid future-window production test.

## Why this review must come before scale-out

The pinned strict-source 576/576 experiment and independent audit showed
**zero learned-vs-frozen test/transfer source or answer gains**, despite
successful Head/Adapter updates. Among the 32 unique test conditions across
all phases, 25 are answerable; 17 have native-document source support inside
the candidate pool and 8 do not. The last test/transfer cohort covers only
**three** observed source families, not a valid wide-scope family sample.
The privileged answer-literal reference is selected using a target answer,
so it is explicitly **not** independently sufficient evidence.

Human semantic adjudication may isolate Reader insufficiency and source
support despite a correct document-level choice. Until the external returns
are independently authenticated and the original frozen Reader is beaten on
prospective tasks, `semantic_citation_precision=null` and
`production_accepted=false`. No PR merge, serving switch or Cell scale-out
is authorized by these research exports.
