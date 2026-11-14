# Hepta Binding V6 — Cross-fact information sufficiency (research only)

Status: `DRAFT / SHADOW_ONLY / DENY_ALL`. Base: research/group-binding-feedback-v5-20261015, PR #2334, SHA `15621518f61d3e202e1f1cf20f577b6d23000dbf`.

## Causal question

V5 froze actual Granite Embedding R2 97M features and trained a 38,466-parameter TokenReader for 8,000 Adam steps over 32 paired-world, 128 candidate **training** examples. All three seeds missed the frozen 100% full-fit criterion (122/128, 125/128, 125/128). Before increasing the Encoder or invoking additional System2 loops, test whether learning a cross-fact residual interaction helps identify the correct ownership-to-storage link.

## Experimental intervention

`binding_v6_bridge.py` adds exactly four bias-free 32x32 matrices (+4,096 parameters) to the unchanged V5 TokenReader. `prepare()` receives the same six public feature/mask tensors and preserves the frozen Encoder. The three physical arms are:

* `cross_fact`: content-addressable fact-to-fact attention over only nonempty facts;
* `global_pool`: one global fact summary with a per-fact learned gate;
* `local`: a per-fact transform with no information exchange between facts.

All arms have 42,562 trainable Reader parameters, identical initialized tensor values per seed, and the same pair-weighted loss. Their CPU arithmetic/latency is **not** assumed identical. This isolates the benefit of differentiated cross-fact binding more narrowly than comparing against a 38,466-parameter unchanged Reader.

`binding_v6_training.py` preserves original V5 training logic and its receipt semantics but fixes a scientific confound: **train-fit success cannot prematurely stop one arm**. All arms execute the same predeclared 8,000 updates, 16 candidates per update, four complete paired-world groups, 250-step diagnostics, three hops, Adam lr .001, pair weight .5, and seeds 41/47/53, unless an actual budget/failure stops that arm. Every update, optimizer tensor allocation and end-to-end fit CPU/wall time is accounted. The V5 fitting code remains byte-identical.

The complete task score (including world-pair consistency) is computed only on the original `reader_train` examples. The V5 source and cache are verified with `checked_design`, which checks original source inventory and prepared-feature identities. No official validation or fresh generated domain is read or scored. No winner is automatically selected, and old-source natural-task retention is **not** established.

## Execute on an already prepared V5 frozen source/cache

Set the following paths to the original pinned materials from V5 (`--v5-output` contains the existing V5 `design.json`). The command creates a **different output** directory and refuses to overwrite anything:

```sh
PYTHONPATH=qualification/stem-cell-v1 python qualification/stem-cell-v1/binding_v6_campaign.py \
  --source /pinned/multirc --snapshot /pinned/granite97 --prepared /pinned/v4-features \
  --previous-main /pinned/v4-main --previous-native /pinned/v4-native \
  --v5-output /pinned/v5-design --output /new/v6-crossfact
python -S qualification/stem-cell-v1/binding_v6_review.py /new/v6-crossfact \
  --output /new/v6-crossfact-independent-review.json
```

A one-seed and small-update profile is permitted for mechanics only (`--seeds 41 --updates 2 --diagnostic-interval 1`); it is labeled `full_profile=false`, cannot be admitted as the three-seed comparison, and cannot produce a model promotion.

Run the focused CPU tests with:

```sh
PYTHONPATH=qualification/stem-cell-v1 python -m unittest \
  test_binding_v6_bridge test_binding_v6_review -v
```

The stdlib reviewer independently reconstructs source-identity world labels and complete-group per-update minibatch indices from seed and original case IDs. It rejects altered predictions, wrong scores, changed CPU/optimizer receipts, missing arms, divergent schedule digests and unsupported authority. Its passing result establishes only **receipt consistency**; it is not hardware attestation, independently repeated pretrained fitting or out-of-distribution evidence.

## Research gates and next branch

1. Actual three-seed Torch pretrained runs must finish on exact source; partial/queued CI is not a passed experiment.
2. Compare cross-fact versus global-pool and local on the same train-only exact schedule and real CPU cost; report recovered/harmed cases per seed, not only pooled accuracy.
3. All three seeds must pass the V5 train-only full128 gate, and both source-held-out proof binding and genuine original MultiRC question-level results must beat controls at registered whole-lifecycle cost before continuation.
4. Only afterward open frozen-verifier feedback, real Group System2 and NDU sparse-control comparisons on independent, future task sources.
5. This adds no multimodal generator, native code emitter, production Encoder selector, OS/GPU effect, FinalUse grant or general FBSDE solver. V1 Q24 and all real Rust owners are unmodified.
