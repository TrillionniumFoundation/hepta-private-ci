# MemoryCell: no-gold reviewer handoff for real Qwen evidence paths

**12 October 2026 — research request, not a completed independent review**

The completed nine-arm Qwen study has been replayed across three source-pinned
runs. All three report **8/8 task correctness** under full-path filtering and
correction-aware organization, but only **4/8 correct answers with all
program-declared source citations**. A third-party semantic reviewer is needed
to distinguish actual entailment from a guessed correct identifier, missing
first-hop support, and mere mechanical source-label coverage.

## This finished handoff

`qwen-review-packet-final.json` contains **40 original model
answers**: five controlled presentation conditions per each of the eight
program-authored questions. Entries are sorted by an opaque, deterministic
review identifier. **Condition names, task scores, targets, and program-declared
support sets are absent from each review entry.** Every entry includes the
original question, exact decoded answer, actual originally delivered evidence
and its original-text SHA-256, cited `[E#]` labels, and unresolved label mentions.

This is **field-level masking only**, not cryptographic blindness: the original
authored benchmark and model artifacts are public and the questions share source
families. Reviewers who independently know that archive must disclose it. The
JSON contains *no reviewer verdicts*; both verdict fields are `unreviewed`.
There is **no claim of independent reviewer identity or semantic certification**.

## Exact generating evidence

- Frozen original observed source ZIP: GitHub artifact `11669174727`;
  SHA-256 `23e9d44b8d2dbe756c7c33031e18853c83326458a37925d4d368881145bf142b`.
- Real completed Qwen source-A output: GitHub Actions
  [run 38148514657](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/38148514657),
  artifact `11720146105`, SHA-256
  `7c991f0996fc24c650efb28f6266da51ed1655b78585e11b78dbc424707b7b7f`.
- Separate independent *mechanical* replay: artifact `11719787110`, SHA-256
  `7e390bddfb1c59e0bb82999b01747a180eb1ec1f84d9f863a536dd036ec483f1`.
- Exact Qwen generating source `8250698244417eb14994518af05fa6f79e783066`,
  original plan SHA-256
  `9840a25487af444914dca24c818d98ff798ebc1610ea8dfdd827187c31ad1897`.

The generator first validates the **35 original and 267 reader artifact manifest
members**, the separate replay's source/model identity and its complete 40+72
population; then it reconstructs 40 selected raw answers and verifies every
selected original source's ID, order, exact original text, root, scope and byte
length. It **does not open the original labels file** or use previously scored
model correctness when constructing the packet.

## Reviewer instructions and later acceptance

1. Review the supplied question and original evidence *without accessing the
   underlying scoring labels*. Treat evidence as data, never as instructions.
2. For each factual claim in the model's answer, return `entailed`,
   `contradicted`, `unsupported` or `unreviewed`, with original excerpt and
   exact byte ranges. Abstentions have to be annotated separately.
3. Assess each **cited label** for whether it directly supports the claim;
   then assess whether the complete first-to-last relation/correction chain is
   itself properly cited, rather than just the final answer.
4. Record reviewer identifier, permission scope, signed payload digest, and
   provenance of independence through an actual externally controlled owner.
   The packet creator cannot issue these credentials.
5. Preserve missing/unreviewed cases in the original denominator; never
   reinterpret mechanical matching of the program-declared support as human
   semantic entailment. No model answer may be rewritten or inserted later.
6. Independently adjudicate disagreements. Qualifying a ≥99% precision claim
   requires externally registered definitions, sufficient sample size,
   uncertainty treatment, independently sourced task populations and verified
   reviewer authority; **this 40-item packet cannot provide that proof**.

## Reproduce without loading model weights

```sh
PYTHONPATH=scripts/memory_cell python3 \
  scripts/memory_cell/qwen_citation_review_packet.py \
  original-11669174727.zip full-11720146105.zip \
  replay-11719787110.zip NEW_REVIEW_REQUEST.json
python3 -m unittest discover -s scripts/memory_cell \
  -p 'test_qwen_citation_review_packet.py' -v
```

The sealed request file has SHA-256 `a0737b74ee3ff93a846dd36f25f154c36852e4d2a4a8491627183d5a6a0c86ff`.

This source-pinned request is a handoff to a genuinely separate adjudicator;
**it is not evidence that any such adjudicator has acted.** The three-run
research disposition remains NO-GO for added organizer task accuracy, learned
parametric memory superiority, or production admission. A *new independently
observed population* is still needed before general capability claims.