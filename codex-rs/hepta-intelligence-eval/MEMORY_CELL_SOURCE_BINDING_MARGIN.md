# Source-only value binding via matched hard negatives

**Research candidate, not production adoption or a measured model benefit.**
The completed pinned Qwen source-writer lowered target negative log-likelihood
without learning to emit the correct identifier on sixteen exposed training
questions. A loss decrease may be compatible with incorrect entity/relation
binding. Increasing adapter steps on the same exposed tasks is not a solution.

`source_binding_margin.py` proposes a separate, explicit contrastive
experiment. It selects one equal-token-length confusable source fact within the
**same original scope**: same entity/different relation first, or same
relation/different entity second. Both positive and negative facts must be
unambiguous members of admitted source-only training examples. No test answer,
task plan, external oracle, unauthorized source, future fact or revoked root is
used. If no admitted negative exists, return an explicit unmatched example; do
not manufacture a null label or silently relabel an unrelated fact.

For exactly the same prompt, the small research objective is

`L = CE(positive) + softplus(0.5 + CE(positive) - CE(negative))`

using the **same tokenizer, prompt and supervised-token count**. A lower loss
is not a factual success; the sign of the log probability *margin* must improve
and held-out factual answers must eventually improve. Both model forwards and
every decoder input token must be charged. Merely reducing the vocabulary
projection count does not make the other forward free.

The first isolated workflow runs bounded real Torch gradients and real
random-weight Qwen2/PEFT compatibility checks. It does not modify the
existing source writer, select a new default loss, train Qwen pretrained
weights, generate held-out responses or issue a reviewer citation ruling.
Before integrating a training option, require (a) this exact-head CI success,
(b) proper source-only negative schedule and total work accounting, (c)
same-reader/same-evidence frozen comparisons, and (d) independently
admitted source families. The eight original authored tasks already saturate
at 8/8 with deterministic event organization and cannot prove improvement.

Keep `semantic_citation_precision=null` and
`production_accepted=false`; retain the current Rust trust, revocation,
rollback and independently governed production gates.
