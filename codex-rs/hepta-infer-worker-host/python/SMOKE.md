# Pinned real-model smoke

`laya_smoke.py` is a qualification-only runner for `laya_retrieval.py`. It is not a product owner, a model-training pipeline, a benchmark proving retrieval efficacy, or permission to invoke an external effect. The production composition requirements remain in README.md.

The model input revision is fixed to `convaiinnovations/laya@d51a65072f7c8eab3c4186b6e062de63d0bd5303`; the SDK is fixed to `NandhaKishorM/laya@4066d5d5fbf08b66c6757ddeedbd797bd7655bc0`. These are chosen immutable inputs, not a claim that either is the latest possible upstream version. Installation checks the SDK's direct VCS provenance. The CI recipe pins the direct inference dependencies and retains installation provenance and the full resolved environment; it is not a fully hermetic, independently attested software supply chain.

Download happens only during explicit qualification preparation. The runner copies the five required checkpoint files out of the immutable Hub snapshot. Any compatibility transformation of tokenizer_config.json is recorded under `hepta.laya.tokenizer-compatibility.v1`, with both original and prepared SHA-256 inventories. The original Hub bytes are never modified. The derivative's pins bind its actual bytes. The worker is then launched with an allowlisted environment and explicit Hub/Transformers offline settings. Offline library flags and read-only files are not an OS-level sandbox against hostile code.

The worker loads real safetensors on CPU, installs a model forward-entry observer and performs two synthetic read-only predictions through the same bounded driver. The report includes actual parameter count, forward calls, load time, cold/warm prediction receipts, software/platform observations and hashes. A passing smoke proves only this concrete load/predict path. It does not prove model grounding, calibration, equal-budget superiority, device attestation, durable product composition, local training, organ credit, computer control or structural plasticity. `production_composition`, `training_executed`, `held_out_efficacy` and `external_effects` remain false.

The parent process has a bounded direct-child timeout and records failure before propagating the exception. It cannot turn a timed-out inference into a successful receipt or unused production reservation. Download/install/load/predict costs are retained separately where observed; there is no claimed p99 from two calls. Reports stay outside the tracked source tree, and CI never uploads weights or rewrites source.

With the reviewed dependencies installed, from the repository root:

```sh
python3 codex-rs/hepta-infer-worker-host/python/laya_smoke.py --output /absolute/new/qualification-directory
```

The output path must not already exist. The companion `test_laya_smoke.py` tests only explicit preparation and input semantics; its three tests are not evidence that real weights ran. Read the exact-candidate `Hepta Laya real-model smoke` result before making any model-execution claim.
