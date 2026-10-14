# MultiRC question vs candidate answer factorial / 2026-10-14

Research-only. Source parent #1981 at `9a4e3a286e6ff0f29787061aea895a2235339096`. Tested code commit `0b49a4095c1fa5c1c604f366c4ac311a5ef115cb` in Draft PR #1991, branch `research/shared-stem-multirc-query-answer-factorial-20261014`. No main merge, deployment, model promotion, historical cost rewriting or training-policy change.

## Question sensitivity cannot be equated with answer sensitivity

The existing blind MultiRC stress test swapped the whole question+candidate pair. This cannot isolate whether a trained Reader depends on the question or the candidate string. The new `multirc_query_factorial.py` freezes the **same trained, sealed Reader** and builds four question × candidate combinations for each source passage: original pair 0/0 and 1/1; swapped cross-pairs 0/1 and 1/0. All four query embeddings are physically recomputed while the passage feature is encoded **once per source**. A combined swap must match the separately sealed earlier evidence stress; original logits must match the prelabel original prediction seal.

Interventions take place **after model prediction sealing and before any validation label is read**. No counterfactual label is created; these cross-pairs may be semantically unnatural, so only positive-class probability movement and descriptive near-zero counts (registered epsilon 0.001) are meaningful. Extra computation is charged in a new strict ledger and is never presented as part of the original task's inference cost. Unknown operators, changed weights, invalid source data, altered seals, storage overshoot or inconsistent replays all stop publication.

## Actual local evidence

Two complete explicit source tests: **597/597 distinct planned and executed tests each**, no errors, failures, skips, expected failures or discovery errors, with identical test identities and SHA256 for all 55 test files. New 10 focused PyTorch tests passed. Initial fixture test incorrectly used a 1024-byte cap while the generated input used less backing store; this resulted in one legitimate test failure, retained. The correction used a truly larger backing tensor; it did not change the meter or admission threshold. Python compileall and YAML parsing passed. Four tested files' remote Git blobs exactly match the local bytes; cumulative patch applies to #1981 source slice and replays byte-for-byte.

The tiny **trained synthetic** fixture has four passages and eight questions. It executed four real passage forwards, 16 query embeddings, 16 Reader calls and 3,392 observed inference formula operations. The mean absolute probability movement was **zero for question-only, answer-only and combined** interventions, and 8/8 questions in each category were within 0.001. This is evidence of **weak/no sensitivity on that fixture**, not successful conditional comprehension; neither natural language generalization nor real pretrained MultiRC result is established.

## Hosted and scientific boundaries

The pinned original workflow adds a focused source test, real stock random-weight Transformer compatibility check and a separate public ModernBERT + human-annotated MultiRC question/answer factorial before scoring. At evidence preparation these jobs were queued; no hosted pretrained pass, question-dependence gain, energy efficiency or real dataset score is attributed to this commit. The project does not enable NDU/SYSTEM2, persistent multi-user caches, modalities, 1024/4096 native Cell serving or 10T/100T equivalence by this change.
