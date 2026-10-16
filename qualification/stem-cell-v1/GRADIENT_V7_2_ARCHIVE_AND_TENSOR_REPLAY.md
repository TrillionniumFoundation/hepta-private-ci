# Hepta Bridge V7.2: original V6 evidence readback and mandatory tensor-level candidate review

**Status:** `DRAFT / SHADOW_ONLY / DENY_ALL`. This is an additive child of the existing
[PR #2383](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/2383) V7.1
research branch. No production owner, Q24 protocol, selected Stem, NDU permission,
CAS/CNS/FinalUse, or original V6 neural experiment is modified. No automatic Cell split.

## Actual new work, not a hypothetical suite

The prior V7.1 reviewer recomputed training-record arithmetic and scanned named
candidate `.pt` file SHA-256, but **could not decode the tensor values**. A
rehashed arbitrary payload could still appear in a synthetic receipt. V7.2
adds an independent restricted Torch state dictionary decoder, true original
source/plan replay, and a hard numeric-checkpoint acceptance in the actual CLI.
It does **not** run the 97M Granite model or make the 9×500 V7.1 training run.

### Actually executed original V6 archive readback

The *previously generated* original V6 evidence ZIP was recovered from the
user's file Library (not created or altered during this run):

- Name: `hepta_bridge_learning_v6_20261015.zip`
- Original byte length: `20,928,479`
- SHA256: `197a5c68eb892970e6a7c7da4030fd2f468a3bf78a5cedfaf4c2667d3e54c58a`
- Archive inventory: **212 entries including the manifest**, all 211 manifest-listed
  payload SHA256 hashes/lengths independently checked.
- Reopened actual **3 saved Bridge warmup** and **9 original continuation** checkpoint
  byte streams, independently decoding each as **22 named CPU FP32 tensors / 42,562
  parameters**. Both historical training and execution parameter SHA256 encodings
  were recomputed from the numeric bytes and matched the original stored manifests.
- Independently checked **128 original synthetic binding TRAIN cases**, including
  four-case paired worlds, fact-derived true labels, exact source text hashes,
  and **3,909 original natural MultiRC TRAIN candidates**; each of the three
  seeded 500-step train-only sampling plans was reconstructed from immutable
  source records and checked against the archived run.
- Original V6 retains **failed global contrastive retention**; neither this new
  readback nor a successful CRC/hash check repairs or reruns that experiment.

A further positive strict-admission test extracted the **actual three original
V6 warmup weight/manifest bytes** into an isolated scratch tree and paired them
with nine explicitly **synthetic Torch-generated** future candidate checkpoints.
The strict original identity + numerical tensor admission accepted this correctly
pinned *mechanism fixture*, while tampered/rehashed variants failed. It does
**not** mean nine new pretrained updates happened.

The source-only replay ran under **`python -S`**, without importing PyTorch.
The sanitized, deterministic output is retained in
`V6_ORIGINAL_ARCHIVE_REPLAY_20261015.json` (report SHA256
`9dc31aa282b0d411a5475b376413bb0ebbde0201c968fa90b0047b4ff025c3e4`).
No original weight tensors, raw source passages, Encoder binaries, or token
feature caches are committed to Git.

### Added full-candidate post-training acceptance

`bridge_gradient_review.py` now has two distinct entrypoints:

- `review(...)`: ledger-only historical method, preserved for explicitly
  **synthetic** unit fixtures. Its returned field
  `trained_weight_numerical_replay_performed` remains `false`.
- `review_complete(...)` and the **actual command-line entrypoint**: requires
  the preceding full nine-arm receipt audit **and** the Torch-free numerical
  decode of each of the **nine newly saved** model `.pt` files plus their three
  real original V6 warmups. Rejects altered/rehashed tensor weights, wrong
  seed, architecture, initialization fingerprint or changed original parent.
  It additionally requires the **original frozen V6 design, completed warmup
  receipt and all three actual Bridge warmup checkpoint SHA256s**, pinned in
  the independent auditor. Rehashing a substitute starting model fails.
  The actual CLI has **no flag to bypass** this tensor-level/origin replay.

Optional `--original-v6-zip` further requires the exact original full archive
bytes and compares its design with the live V6 tree; this is a historical
lineage check, not an external publisher signature or a new pretrained forward.

A private `_synthetic_test_only` function parameter exists solely to test
artificial Torch-generated checkpoint bytes; it is **not exposed by either
command-line interface**, and synthetic test results explicitly cannot claim
pinned original pretrained provenance.

The decoder allows only bounded CPU FP32 `OrderedDict` state dictionaries and
three specifically whitelisted pickle globals. No arbitrary Torch code is
imported, no GPU/device tensor or noncontiguous/aliased storage is admitted,
file inputs are opened with no-follow descriptor checks where supported, and
invalid/partial ZIPs fail closed.

## Reproduce against existing files

```sh
# Python standard-library only: truly reopens the ORIGINAL V6 ZIP bytes.
python -S qualification/stem-cell-v1/bridge_gradient_archive_replay.py \
  --original-v6-zip /private/original/hepta_bridge_learning_v6_20261015.zip \
  --report /private/results/V6_ORIGINAL_ARCHIVE_REPLAY_20261015.json

# Run after the genuine 9-arm V7.1 model training, in a separate interpreter.
python -S qualification/stem-cell-v1/bridge_gradient_review.py \
  --previous-v6 /private/original/reader-v6-bridge \
  --output /private/results/bridge-gradient-v7-1 \
  --original-v6-zip /private/original/hepta_bridge_learning_v6_20261015.zip \
  --review /private/results/bridge-gradient-review-with-tensor-replay.json

# Synthetic/test-mode numerical regression and required source contract tests.
cd qualification/stem-cell-v1
python -m unittest -q test_bridge_gradient_guard test_bridge_gradient_review \
  test_bridge_gradient_archive_replay
python -O -m unittest -q test_bridge_gradient_guard test_bridge_gradient_review \
  test_bridge_gradient_archive_replay
```

Local test outcome on PyTorch 2.10.0+cpu: **53/53** normal Python and **53/53**
Python `-O` tests passed, including actual anchored warmup positives and explicit
negative source/weight/path/unsafe-pickle cases. The original historical
archive audit ran additionally as a separate `python -S` process.

The actual V6 ZIP can be supplied from the private file Library; the research
checkout does not vendor 20.9 MB of historical saved weights.

## Unresolved, explicitly denied claims

No authentic original Granite97 model **weights** or original saved TokenBank
**tensor cache** were present in this container. The original V6 ZIP and
separate V4/V5/V7 archived receipts expressly omit these materials. Therefore
full **nine new** V7.1 source-matched pretrained training campaigns have **not**
been executed, no prospective source-disjoint utility was measured, and no NDU
System2/CellSplit/CNS production selection can follow from this result.

Numeric reconstruction of stored tensors does *not* prove that a particular
optimizer executed earlier, nor that the external publisher, host identity,
or evaluation chronology was independently authenticated. No energy, p99,
complete optimizer FLOPs, 10T/100T equivalence or multimodal generation claim.
The next scientific action is to reacquire the exact original checkpoint,
preprocessor/tokenizer and cached input material with their verified hashes;
then execute all nine physical training arms and compare external future
outcomes under registered whole-lifecycle budgets.
