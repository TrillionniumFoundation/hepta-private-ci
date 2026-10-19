# LoCoMo publisher-support refusal boundary — exact pinned 2026-10-13 input

**Research-only; no original gold answer text goes to the Reader.**

The published LoCoMo 16-question evaluation cohort was rechecked from three
immutable Actions ZIP byte pins (not from synthetic fixtures):

| Source | Artifact | Actual SHA-256 |
| --- | --- | --- |
| Public history and question population | 11728164433 | `51e18514c68f31220f4dcd072914f6e015aa9733b6c5b4a4d4e3b14dac25ec37` |
| Frozen 6-arm lexical/recent decisions | 11729394703 | `3fb1c3272314d31b42ece1c74aa0250e2ecb06c6060cb011071d4654fef6f097` |
| Publisher target labels, scorer side only | 11728856834 | `d09823324003ab431301e60fbbb280e216ca03b686e178d4f36fb6d492981978` |

The **16 exact preregistered evaluation questions**, across **two published
source-family proxies**, have **13 answerable examples each with complete
publisher support**, and **three publisher-unanswerable examples EACH WITH
ONE original in-scope supporting source**. There are **zero missing/partially
unresolved support sets** and **zero out-of-pool support identities**.
Fourteen examples have one supported source and two have two. The maximum
serialized support-document text across a question is **554 UTF-8 bytes**.
These are native document-source annotations, **not independently reviewed
window entailment**.

An earlier preflight incorrectly assumed `unanswerable => no supporting
documents`. That fails for all three native unanswerable-with-support
examples. The new explicit protocol state `publisher_refusal_support`
**retains these original sources and asks the unchanged frozen Reader
whether it abstains even with publisher-relevant context**.
`unanswerable_empty` remains reserved for cases with *truly empty* support.
`support_unavailable` remains reserved for absent, unresolved or too-large
support; it is not a manufactured no-evidence answer.

The frozen Qwen Reader sees only the original question, original supplied
source bytes and the existing identical prompt/model budget. The
`publisher_refusal_support` category is a **post-hoc receipt/plan field**,
never inserted as a Reader instruction. The publisher answer, ground-truth
unanswerability and reviewer verdicts remain outside the generation node.
Post-generation scoring compares to the original pinned publisher labels,
including their answerability classes, using the unchanged two lexical
retrieval controls and every originally planned question. Source and model
hashes, omissions, failures and actual Reader executions remain explicit.

The original frozen retrieval contained the **entire publisher support set**
for **8/16** questions under lexical-k4 and **10/16** under lexical-k8.
These are *complete-document-source coverage* counts, not correct Reader
answers, citation entailment or learning benefit. They motivate testing
actual Reader capacity with source-present inputs before allocating larger
Head or Cell budgets.

The new AST-identical formatter pipeline fixes the separate Ruff syntax
format prerequisite; **format pass does not imply model generation success**.
Even if the new publisher-supported Qwen diagnostic succeeds, publisher
source IDs are privileged weak labels, not blinded independent sufficiency
reviews. `production_accepted=false`, `semantic_citation_precision=null`,
and no additional Cell scaling is qualified.
