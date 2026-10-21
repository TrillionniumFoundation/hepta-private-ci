# MemoryCell: sealed source-first blind sufficiency handoff (2026-10-16)

**Result: 32 original source-only review tickets exported and SHA-pinned; 0 independent reviewer verdicts obtained. Scientific status: DENY_ALL.** This uses the SAME eight previously exposed LoCoMo conversation roots already evaluated by the 32-call and 48-call frozen Smol135 experiments. It creates **no** prospective source families, model inferences, training updates, authenticated human judgments, citation entailment certification, or production permission.

## Why this is the appropriate next gate

The prior model's 48-call format experiment reduced answer-JSON echo but generated **0/8 strictly correct answers** in each of the six conditions. A post-seal publisher-answer literal audit found that only **2/8** marked witness texts contained the complete normalized publisher answer. Literal absence is **not proof of insufficiency**, and presence is **not proof of entailment**. Before attributing failures to Reader model size, a separate person must judge whether the *delivered context alone* is sufficient to answer, without access to publisher targets or to model outputs. An existing `locomo_sufficiency_worklist.py` covers another historical 16-question/2-family study; this adapter is restricted to the actual eight roots from the current physical experiments, not another memory store.

## Observed source-first export

Exact original registered pre-generation plan SHA-256: `6e35124fd130c1836c8146b0ab66f26f957fe710d4c03b7fe4183db65e936c60`.

Original sealed input SHA-256: `fa7d9e676f9aca8f7c524e6f592cabb88a22c490a8c441db4bd6a8e05fbc6033`.

The local coordinator used a new random private key to produce 32 HMAC-blinded review tickets, shuffled without publishing their condition names. Tickets display an original question and **only actually delivered** `[E1]...` evidence, speaker and unmodified text. They contain no model answers, publisher answers, gold labels or condition mapping. The companion private source/arm map and random secret stay in the isolated work environment and are **not committed to Git**.

| Preserved item | Observed |
| --- | --- |
| Previously published source roots | 8 |
| Source-first review tickets | 32 |
| Frozen no-evidence/lexical/witness/lesion cases | 8 each, arm mapping private |
| New neural-model calls | 0 |
| Actual independent review decisions | 0 |
| Human-authenticated sufficient contexts | 0 |
| Production acceptance | `false` |

Sanitized public receipt: `scripts/memory_cell/data/locomo-blind-source-first-20261016.json`, file SHA-256 `0157a1358fa28072d8e95b74b22bc708325821a259c54c5ac6309468e1ec500d`. Original blind packet canonical SHA-256: `110270506a0ced9abea92f52682d624c4cf94c39318b90a75e5ec245aa64abad`. Private map canonical SHA-256: `16e3231766215bf72aa8919661b7ecebed3ed560f16ff16960dfd3d0ba684448`; a digest of the private map **does not disclose or authorize the mapping**.

## Review protocol and safe return

A source-only reviewer independently chooses `sufficient`, `insufficient`, `conflicting`, or `unassessable`. A `sufficient` claim requires an answer derived by that reviewer, one or more exact UTF-8 byte-offset source spans, and no unresolved contradiction. Conflicts identify delivered labels; the absence of evidence may be a valid insufficient decision, not a failed inference. No label or reference outside the delivered packet can be counted as support. A second reviewer must return all 32 tickets independently; disagreements stay unresolved, not majority-washed.

The review-return validator checks exact packet SHA, all 64 paired rows, duplicate/missing tickets, IDs, real source bytes, UTF-8 boundaries and conflicting source labels. It does **not** authenticate a reviewer because two distinct *claimed usernames* are not independent identities. Reviewer attestations and provenance must be validated by an external authority before any sufficiency or semantic conclusion is accepted. The code deliberately emits `reviewer_identities_externally_authenticated=false` and `source_sufficiency_human_certified=false` even when the two returned sheets agree.

If actual independent reviewers return their forms, separate source-first adjudication must be completed **before** unblinding, answer review, reference-reader selection or any parameter-learning comparison. These eight old roots remain development diagnostics and cannot become new future-window observations through review alone.

## Commands and replication

From a complete repository checkout with the **original** local, SHA-pinned, pre-answer source files:

```sh
PYTHONPATH=scripts/memory_cell python3 scripts/memory_cell/locomo_blind_sufficiency.py export \
  --original-plan PRIVATE_ORIGINAL_PLAN.json \
  --sealed-sources PRIVATE_ORIGINAL_SEALED_INPUTS.json \
  --secret-file PRIVATE_RANDOM_SECRET_FILE_AT_LEAST_32_BYTES \
  --private-output-dir NEW_PRIVATE_REVIEW_DIR

PYTHONPATH=scripts/memory_cell python3 -m unittest discover \
  -s scripts/memory_cell -p 'test_locomo_blind_sufficiency.py' -v

PYTHONPATH=scripts/memory_cell python3 scripts/memory_cell/locomo_blind_sufficiency.py audit-public \
  --receipt scripts/memory_cell/data/locomo-blind-source-first-20261016.json
```

Never upload the random secret, reviewer questions, original dialogue text, blind-map JSON or raw Reader answers into public PR comments or Actions artifacts. GitHub CI executes **only** source-only tests and the sanitized fixed public receipt audit. That CI verifies no new model improvement; it cannot replace independent human review, production withdrawal/recovery, complete lifecycle cost or required `blocking-ci` and Architecture checks.
