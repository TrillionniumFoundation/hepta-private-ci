# Pairwise-source Shadow Head — research-only controlled candidate

**Motivation.** The pinned successful 576/576 native six-arm matrix has 23/30
persistent Head checkpoints with improved TRAIN weak-source loss but 0/30
changed TRAIN top-1 decisions. Independently verified test+transfer comparisons
also lack a positive native-source gain. The train-only residual-amplification
grid improved some test choices but regressed on transfer, so turning up
a scalar on existing weak-label logsumexp is not an accepted remedy.

**Intervention A (separate from the original six arms).**
`stem_pairwise_shadow.fit_pairwise_shadow` uses exactly the existing sealed
TRAIN Supervisions and frozen paired Encoder features. On source-labelled
examples with both positive and weak unlabelled candidate windows, it applies
bounded SGD to

`softplus(margin + max(weak_negative_logits) - max(positive_logits))`.

The last null/abstention logit is omitted entirely. Unanswerable, unresolved,
single-candidate and all-positive examples cannot forge contrastive updates.
Both rejected-example counts and resumed optimizer steps are recorded.
The null parameter tensors must remain byte-identical; original source
Reader weights, prompt, candidate pool, original six Heads and their 576
policy attempts are unchanged. Imported frozen Head state is individually
sealed and may be reloaded without momentum.

**Control and evidence status.** Native document-level support is weak:
unannotated negatives are NOT independently verified contradictions. This
candidate is not a primary matrix seventh arm, not a production Head, not
yet evaluated on frozen-matched test/transfer sources, and may overfit.
Do not use select/test/transfer answers or support annotations to fit,
select margin, choose learning rate or adjust checkpoint budgets.

The bounded real-CPU PyTorch mechanics workflow
`.github/workflows/hepta-memory-stem-pairwise-shadow.yml` runs pure
synthetic tests without pretrained downloads. A native experiment can be
considered only after that workflow passes with exact source pins. It
must independently show correct supported source choices and Reader answers,
not merely reduced training loss or parameter changes. Until then,
`production_accepted=false`, citation entailment precision null, scale-out
blocked. No main or production change is authorized.
