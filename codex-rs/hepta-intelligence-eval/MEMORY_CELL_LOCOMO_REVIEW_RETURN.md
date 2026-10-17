# LoCoMo external review-return validation (research-only)

The original source-first sufficiency packet and separate unmodified-answer
citation packet contain 32 paired k4/k8 cases from 16 publicly exposed LoCoMo
questions and only two public conversation-family proxies. The original
source-only review opens neither gold targets nor Reader answers. The answer
review is a separate later assignment with the original Reader output only.

locomo_review_reconciliation.py validates exact worklist/manifest hashes,
32-case identity and order, nested same-question evidence, immutable UTF-8
source bytes, source-only answer/support spans and each occurrence of a Reader
emitted citation with separately identified preceding answer-claim byte spans.
Missing evidence, answers and unreviewed citations retain their planned
denominators. It cannot change answers, add citations or turn structural labels
into entailed claims.

A reviewer name and timestamp inside a return are not cryptographic identity,
institutional authority or evidence of actual source-first viewing order.
No signing keys, independent human authorization, verified semantic precision,
family confidence interval or prospective time window are issued by this code.
Even a full all-true return can only report unverified claimed proportions.
Independently verified semantic precision stays null; production_accepted=false.

Commands (from a separately archived, original SHA-pinned worklist directory):

    python3 scripts/memory_cell/locomo_review_reconciliation.py template PACKET NEW_EMPTY_RETURNS
    python3 scripts/memory_cell/locomo_review_reconciliation.py audit PACKET SOURCE_RETURN ANSWER_RETURN NEW_REPORT

The read-only hosted workflow rebuilds only the three pinned public research
source/Reader artifacts, tests original-return structure, and publishes empty
review slots. It does not fabricate reviewers, judgments or a training gain.
Formal acceptance requires independent source-access-isolated review and
external owner identity/signature verification with real qualified histories.
