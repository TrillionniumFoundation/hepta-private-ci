# Source-family, raw-answer and full-cost scientific admission check

Research only. Branch ancestry: `TrillionniumFoundation/hepta-private-ci` PR #2319,
parent `dc7887041dbbe66fd4023b8345111d7f365afc95`. Strictly additive.
This module is **not** an independent evaluator, signer, runtime policy owner,
production gate, selected model, or neural FBSDE solver.

## Two distinct interfaces

1. `--public-archive A --original-trial-archive B`: reopens original public
   AG News labels in pinned pretrained-feature archive A, checks all 128 source
   rows and 64/32/32 census, verifies completed earlier real trial ZIP B by its
   exact outer SHA, recomputes **all** fixed8 and NDU decisions over **each of
   three repeats in both Python modes**, and compares raw heldout class
   probabilities, source ID inventories, original source labels, actual SGD and
   observed local CPU. The archive hashes are fixed source observations, not
   independently signed attestations. This is a **retrospective same-data**
   comparison. It must return `RESEARCH_ONLY_DENY_ALL` and no NDU task lift.
2. `--prospective-packet P`: validates the future-study *shape* without allowing
   caller-supplied strings/booleans to constitute independent attestation. Requires
   exactly the named cheap and same-information controls; a frozen objective,
   original complete source census, true source-family/window identifiers rather
   than row IDs, exact label-blind prediction seal, separate outcome map, and all
   named training, material, inference, pilot, verification, selection, migration
   cost phases. Unknown physical cost is `null` and blocks cost comparisons.
   Computes paired **family-level**, not row-level, one-sided exact sign
   statistics and Holm correction for two prespecified controls. These tests
   assume independent exchangeable family signs; code cannot establish that
   assumption from source string IDs. No claim of globally valid 95% coverage.

Even a perfect synthetic positive example remains **unqualified** without
independently authenticated source-family, evaluator/time and physical-cost
receipts. No trusted signing root is available to this research-only module;
therefore it *never* issues an acceptance or FinalUse token. Input booleans
claiming independent approval do not create that authority.

### Observed original negative

Pinned public-feature ZIP SHA256:
`195dfb9e5bedaf5cee7fe8b2994a10f7ebaaf9ecca2a3a94bb77b0185a4337a7`

Pinned completed earlier study ZIP SHA256:
`c78cfe148e6d9544450836202f4da0f9bc5d93f980c96362238945b20a67898f`

Actual source contains 128 distinct records but record IDs are **not certified
independent news story families**. All six replays (3 repeats × 2 modes) have
fixed8 and NDU exactly equal predictions, fixed8=26/32 correct and NDU=26/32,
paired NDU wins/losses=0/0. NDU physically executed 128 SGD steps versus fixed8
8 and cost more measured local CPU in each repeat. This proves a conditional
same-snapshot observed-result/cached-input-cost dominance, **not** a future task
statistical claim, complete online TCO or general NDU impossibility theorem.
Raw original text, original labels, logits and Head weights remain only in
archived source files, not newly committed public Git files.

### Reproduce

```sh
D=experiments/ndu_tree_fbsde_gates/merton/qualification
python -m unittest discover -s "$D" -p 'test_*.py' -v
python -O -m unittest discover -s "$D" -p 'test_*.py' -v
python "$D/science_gate.py" --public-archive /path/original-source.zip \
  --original-trial-archive /path/original-study.zip \
  --output /tmp/hepta-ndu-science-negative.json
```

Existing `blocking-ci`, original original-human P0 source gate, source-selected
model authority, and the independent evaluator remain mandatory. Upstream P0
V12 real material run `38686023757` failed; V13 fix PR #2378 had not yet
produced a successful physical source archive at the time of this research.
Do not fabricate new-source model results or use an unrelated model lineage to
fill a missing original record. No automatic main merge or production activation.
