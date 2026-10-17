# V12 — original pretrained model loading and Head identity fault isolation

DRAFT / SHADOW_ONLY / HOLD_NO_GO / DENY_ALL. Exact original V9 failure parent
`adcc7f847c0589bd388ebb054e98b6c5c96856a2`, PR #2679. Additive
read-only diagnostic branch: never change V1/V3 source, previous evidence,
main, model selection, Worker, CAS/CNS, NDU, FinalUse or physical Cell Split.

## Why this exists

Original V9 hosted Action #39034261534 obtained a genuine Granite97 8-case
physical selected-inference report. Granite47 and mmBERT-small failed at
**strict trained Head checkpoint byte parity**. The mmBERT loader also logged
that `embeddings.tok_embeddings.weight` was newly initialized and not
restored from the pinned pretrained checkpoint. A safetensors SHA alone
establishes serialized input identity, **not** a complete, correctly mapped
pretrained model. Historical mmBERT scores must not rank an optimal Stem
until this is resolved and the comparison is re-run.

V12 diagnoses, not waives, the blockers: reopens each original SHA-verified
safetensors file, obtains the actual Transformers `output_loading_info` for
`AutoModel` on Granite47/97/mmBERT140, and tests the separately named
`AutoModelForMaskedLM` complete-checkpoint loading profile for mmBERT only.
For each candidate/profile, it physically recomputes 64 original FIT plus
8 original selected HELD pretrained Encoder features, trains the unchanged
6,914-parameter-per-Cell gated Head for 100 updates, and separately records
**initial vs trained Head SHA equality** and frozen V3 selected-row
probability drift for learned, untrained and centroid arms.

An original serialized weight not restored to the model (any nonempty
`missing_keys`, `mismatched_keys`, or loader error) is a strict **NO-GO**
regardless of downstream correctness or Head checkpoint comparisons. The
full-MLM experimental path is **not** granted production selection even if
it has no missing keys: a fresh full 96-case paired research producer and
independent reviewer would still be required. The original prior TEST gold
is already exposed, and this is historical debugging, not prospective
calibration, negative-transfer or new-source generalization.

`independent_loading_review_v12.py` imports **neither** the producer nor any
Torch model. It reopens exact V5 archived original provenance, checks loader
missing-key counts, rejects asserted success with missing weights, checks
Head hashes, source, original forward counts, probability drift, costs and
unconditional lack of authority. A successful diagnostic workflow means only
that its diagnostic experiment completed, NOT that the candidate loaded
correctly. A failed job remains a recorded blocker, not waived.

## Source tests

```
python -m unittest discover -s qualification/stem-original-loading-v12 -p 'test_*.py' -v
python -O -m unittest discover -s qualification/stem-original-loading-v12 -p 'test_*.py' -v
```

Still blocked: model issuer signatures, independent new time/source-family
HELDOUT, same-machine 421M lifecycle and real target-host 4096-Cell
p95/p99/RSS/GPU/energy/WAL/recovery, genuine learning retention and NDU
net utility, signed FinalUse, and any physical Split or product model change.


## Physical diagnostic trigger

The push-only exact-branch lane is the authoritative place to acquire the
pinned original material and run the four read-only loader profiles. This
source-only document change deliberately triggers that lane; it does not
change model code, weights, scoring, or any authority posture.
