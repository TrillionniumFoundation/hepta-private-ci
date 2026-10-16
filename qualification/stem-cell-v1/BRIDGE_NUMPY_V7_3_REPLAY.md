# V7.3 — independent numeric Bridge forward over authentic frozen V6 weights

**2026-10-15 · Research only · DRAFT / SHADOW_ONLY / DENY_ALL · no production model selection, no Cell Split, no NDU authority.**

## Material provenance and scope

This increment continues [V7.2 / PR #2383](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/2383) from the exact original V6 research lineage, without changing the native Neuron V1/Q24, model owner, Encoder, Worker, CAS/CNS/FinalUse, existing original V6 checkpoints or `main`.

Original recovered archive: `hepta_bridge_learning_v6_20261015.zip`, exactly **20,928,479 bytes**, SHA256 `197a5c68eb892970e6a7c7da4030fd2f468a3bf78a5cedfaf4c2667d3e54c58a`. The previous V7.2 restricted decoder independently admitted the original 12 checkpoint tensors: three `bridge/warmup.pt` and nine historical `bridge/{natural_only,replay,contrastive}.pt`, each 22 CPU FP32 tensor names and 42,562 values. The ZIP is stored separately in the user's file Library. The model tensors are **not committed**.

The numerical operator contract is separately pinned to historical Git blob `token_reader.py@ca814a855c35e3d6fcf50883dba6d66b325d5c54` and `bridge_reader.py@a9e7fba84fdff03e3f65c9d67bf42d59ee931cd1`, as they appear in the pinned V6 lineage. This research source is not an independent model-issuer attestation.

## What is implemented

1. `bridge_gradient_archive_replay.decode_fp32_checkpoint(..., include_tensor_bytes=True)` adds an **optional private in-process** raw FP32 tensor projection *after* every existing restricted Torch-ZIP/pickle/geometry/finiteness/alias check. The default metadata-only return and digest semantics remain unchanged. Never serialize or publish tensor bytes.
2. `bridge_numpy_forward.py` independently executes the **entire frozen BridgeReader forward** in NumPy (no `torch` import): feature layer-normalization, distinct question/candidate attention, eight-way relation construction, masked Q/K/V fact-to-fact residual, recomputed token keys, token and fact attention, bounded recurrent gating, feedback, and final logits. Every input and tensor has a typed, bounded shape; no arbitrary checkpoint constructor, pretrained weight fetch, raw-effect output, or generated-code executor exists.
3. `bridge_numpy_reference_torch.py` is a **test-only** second forward transcription using PyTorch math for numerical comparison. It is not the original imported runtime. The two implementations are separately authored from the pinned V6 operator definitions; agreeing on synthetic features is evidence of numeric equivalence for those cases, not semantic correctness.
4. `bridge_numpy_original_v6_parity.py` recomputes all twelve **authentic** frozen checkpoint outputs against that test-only PyTorch reference, using a preregistered synthetic FP32 token probe. It emits only hashes/aggregate errors, never weight tensors, raw tokens or labels. `V6_BRIDGE_NUMPY_PARITY_20261015.json` is the completed source/weight-bound receipt.
5. `bridge_numpy_receipt.py` provides an optional future-feature independent parity gate requiring a **separately supplied expected** model SHA256 and manifest SHA256, six sealed NPZ feature arrays, principal/purpose/generation/source identifiers, and a separate presealed external logits file. It independently decodes checkpoint tensors and recomputes logits, rejecting a probability decision-class flip even if numeric differences fall within tolerance. NPY declared header size/dtype is checked **before allocation**; ZIP/JSON/tensor bytes are bounded and symlinks denied. The submitted SHA values do **not** by themselves prove truthful original-feature provenance or immutable prediction chronology.

## Results actually executed locally

- CPU: PyTorch 2.10.0+cpu and NumPy 2.3.5, one Torch thread, three true seeds `41/47/53` and four archived Bridge checkpoints per seed.
- Each model uses the same **synthetic, non-Granite** three-case feature probe, 4 fact slots x 5 token slots, 384 channels; masks include a padded token and a wholly absent fact.
- Recompute three causally sequential Reader hops and compare output state, candidate logits, fact attention and token attention per hop; preregistered maximum absolute numeric tolerance **0.0015**.
- **12/12 actual saved pretrained Bridge checkpoints PASS.** Maximum absolute difference **4.0531158447265625e-06**, using actual historical 42,562-scalar checkpoint byte streams and a separate Torch math transcription.
- Additional tests cover all-masked input, depth 1/3/8, recurrent resets, external feedback, fact permutation, altered weights, nonfinite/badly typed masks, malicious large NPY header and external-logit/class spoofing.
- Inherited V7.2 source/receipt tests are retained. Execute local normal and optimized-mode suites on the exact tree before making a test-success claim; **do not count skipped original-weight cases as pretrained success.**

## Reproduce

```bash
# Acquire the exact SHA-pinned historical ZIP in a private local directory.
export HEPTA_ORIGINAL_V6_ZIP=/sealed/hepta_bridge_learning_v6_20261015.zip
export HEPTA_V6_ORIGINAL_ARCHIVE="$HEPTA_ORIGINAL_V6_ZIP"
cd qualification/stem-cell-v1
python -m unittest -q test_bridge_gradient_guard test_bridge_gradient_review \
  test_bridge_gradient_archive_replay test_bridge_numpy_forward test_bridge_numpy_receipt
python -O -m unittest -q test_bridge_gradient_guard test_bridge_gradient_review \
  test_bridge_gradient_archive_replay test_bridge_numpy_forward test_bridge_numpy_receipt
python bridge_numpy_original_v6_parity.py \
  --original-v6-zip "$HEPTA_ORIGINAL_V6_ZIP" \
  --output /sealed/BRIDGE_NUMPY_PARITY_NEW.json
```

A separate presealed feature replay (not executable against the missing authentic TokenBank yet):

```bash
python bridge_numpy_receipt.py \
  --checkpoint /private/frozen-candidate.pt --checkpoint-sha256 EXPECTED_64_HEX \
  --archive /private/feature.npz --manifest /private/feature-manifest.json \
  --manifest-sha256 EXPECTED_INDEPENDENTLY_PRESEALED_64_HEX \
  --external /private/presealed-logits.json --output /sealed/independent-parity.json
```

The NPZ must have exactly `facts`, `question`, `candidate`, `fact_mask`, `question_mask`, `candidate_mask`, each in a distinct `.npy` member. Its manifest must bind the original case identities, per-case source SHA256, original Encoder/tokenizer/preprocessor digest, authorization principal, purpose and generation, total archive digest and per-array raw byte SHA256. Original user text, private labels and free-form effects are not accepted.

## Scientific boundary / next actual model experiment

**Original 97M Granite Encoder weights, its exact tokenizer/preprocessor runtime and original TokenBank feature tensors were not present in the authoring environment; network fetch failed due unavailable DNS.** Historical V4/V5/V6/V7 evidence archives retain hashes and checkpoint tensors but intentionally omit original frozen Encoder and cached token feature bytes. Therefore **no new Granite forward, no new nine-arm V7.1 candidate training, no original-source semantic prediction, no future old-task retention gain, no multimodal generation, and no 10T/100T equivalence** was executed or inferred by this V7.3 numerical test.

Next physical gate: acquire/pin the historical Encoder+TokenBank/official MultiRC bytes, verify original-token SHA and known historical inference outputs, then run all **nine** V7.1 arms and make the optional independent NumPy feature-to-logit verifier replay exact candidate model predictions on original future source-disjoint cases before claiming learning progress. Model selection, cell split, and NDU optimization remain independently gated. This work is **research-only and non-promotable**.
