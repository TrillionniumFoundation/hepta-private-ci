# Learned question-to-cell routing

This research component fits a small softmax model to source-query observations
and measured expert utilities. Inference accepts exactly `{"question": text}`.
It cannot receive relation metadata, gold answers, a source table or a requested
expert. Feature extraction uses deterministic signed hashes of words, bigrams
and character 3/4-grams. The mapping from these features to experts is learned
by actual gradient updates; no relation-to-cell dispatch is encoded.

```python
from learned_router import fit_router, load_router

router = fit_router(
    source_observations,
    expert_ids=["cell-a", "cell-b", "cell-c"],
    source_sha256=independently_retained_source_digest,
)
receipt = router.save("router.bin")
reader = load_router("router.bin", expected_sha256=receipt["sha256"])
decision = reader.predict({"question": final_question})
```

Each observation is exactly `question`, `utilities` and `reject`. Utilities are
finite values in [0,1] aligned with the declared expert order, obtained only
from the source partition. Explicit unsupported examples and rows whose best
utility is below the registered threshold train a separate reject class.
Positive ties produce soft targets instead of arbitrary expert labels. The
default inference policy requires total probability mass on experts of at least
0.55, and the best expert's probability must exceed the reject probability by
at least 0.05. This allows shared knowledge supported equally by two experts
to route rather than confusing expert ambiguity with unsupported input. The
selected slot is a deterministic expert argmax; a probability tie uses the
first declared expert. These are fixed research thresholds, not claims of
distribution-free or universal unknown-query calibration.

Predictions report `support_confidence` (also exposed as `confidence`),
`expert_confidence`, `reject_probability`, and `margin` (best expert minus
reject). `expert_margin` and `ambiguous_experts` separately describe uncertainty
between experts. Routing an ambiguous positive-support example does not claim
learned expertise discrimination. The named decision rule is pinned in the v2
state artifact so older inference semantics cannot be silently substituted.

`verify_question_splits` rejects normalized exact overlap within/between named
partitions. The caller must additionally enforce fact/entity/temporal splits
appropriate to the experiment and must never derive utilities or configuration
from final outputs. The model records the hash of its exact source observations
and an independently supplied source-provenance hash. It cannot authenticate
that supplied source claim by itself.

State artifacts contain a closed JSON header plus float32 learned weights,
loaded with a retained SHA-256 pin and no pickle. Receipts count both private
parameter bytes and full serialized artifact bytes, as well as actual optimizer
updates. Saves are exclusive so historical artifacts are not overwritten.
Predictions grant no checkpoint installation or source-authorization authority;
the existing owner/frontier admission remains necessary after routing.

The tests fit actual models, hold out entity names and question wordings,
permute observed expert utilities to demonstrate a changed learned mapping,
exercise learned rejection, preserve decisions across exact artifact reload,
and reject privileged input, invalid costs/utilities, source overlap and
tampered states. Lexical generalization here does not demonstrate arbitrary
semantic reasoning, unknown-entity detection or learned expert partitioning.

```bash
PYTHONPATH=scripts/memory_cell_router python -B -m unittest discover \
  -s scripts/memory_cell_router -p 'test_*.py' -v
```
