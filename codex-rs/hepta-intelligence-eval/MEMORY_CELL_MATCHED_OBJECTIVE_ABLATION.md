# Matched-initialization source-objective ablation

## Research question

Does the absence of observed correct source changes in the completed 576/576
native six-arm run arise in part from training the Head with multi-positive
cross entropy **including the null class**, rather than explicitly separating
weak positive source candidates from competing unlabelled candidates?

Prior evidence: original six-arm source accuracy and actual frozen Reader answer
token-F1 were identical across all five learning arms and the frozen baseline;
none emitted a citation marker. Real mini Encoder and LoRA weights changed,
but that did not establish learned QA benefit. A separate pairwise-shadow
contract passed CPU PyTorch unit tests. Its source-only decisions have a
different Head initialization than the original six-arm Head and thus cannot
isolate the causal effect of objective choice.

## Fixed intervention

`stem_native_matched_objectives.py` clones **byte-identical initial Head
weights** for each of two kinds (`linear`, `gated`) and two Cells
(`general`, `temporal`). Both objectives consume exactly the **same
already-admitted TRAIN rows having at least one labelled weak source-positive
window and one other weak-unlabelled candidate window**. Every frozen Encoder
feature vector is reused unchanged. Neither class receives test, transfer,
retention, or selection answer labels during fitting.

| Frozen dimension | Fixed value |
| --- | --- |
| CE objective | Original multi-positive cross entropy including null |
| Pairwise objective | Softplus(1 + hardest weak-negative score − max positive score), no null training |
| Learning rate | SGD 0.03, no momentum |
| Update steps | 128 per Cell and checkpoint per objective |
| Persistent checkpoint budgets | 16 / 32 / 48 TRAIN questions, cumulative |
| Source features | Original exact frozen paired Encoder, no new encoding |
| Initial parameters | Bit-for-bit identical for CE and Pairwise within each kind/Cell |
| Evaluation questions | 8 each: select, retention, test, transfer |
| Score-only decisions | 384 (3 checkpoints × 32 questions × 2 Head kinds × 2 objectives) |
| Additional Reader calls | **Zero** |
| Original six experimental arms | **Unchanged** |

Every fitted Head is written as an independent artifact and reloaded with
SHA-256 parity. Each choice is bound to the same frozen candidate-pool,
question, source family and initial Head SHA, **before reading test/transfer
support annotations**. The post-hoc summary separately counts cases where
pairwise weak-native-source selection beats matched CE and the reverse. A
training loss difference, rank flip, or weak document-level support label is
not equivalent to independently verified entailment or better Reader output.

## Validation, rejection rules and resource boundaries

The complete original 576-attempt matrix, fixed Reader prompts, cached inputs
and trained Heads remain unchanged. A failure in any separate objective or
source-only decision is retained as a failed receipt, not dropped from the
denominator. The CI runs a separate CPU Torch fixture with original Head
training code, and the full pinned native matrix then tests frozen-Encoder
representations with original source timestamps and exact family partitions.

The comparison is a **development ablation**, not a new untouched benchmark.
No held-out outcome is used to tune steps, margin, loss weight, seed, or model
selection; independent prospective source families and a genuine blind
semantic citation judge are still missing. Pairwise wins against CE can justify
a separately registered new-family Reader experiment, not direct production
adoption. `production_accepted=false`; `scale_out_permitted=false`.
