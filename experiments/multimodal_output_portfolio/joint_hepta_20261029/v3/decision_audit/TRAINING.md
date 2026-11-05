# Local neural text-output adaptation

`train_adapter.py` performs supervised training of a rank-limited neural residual on the actual pretrained VLM output head. The visual/language backbone, original output weights, tied input embeddings, and image diffusion generator remain frozen. Every update executes the actual image-conditioned model forward; assistant-answer tokens receive cross entropy only after processor token-prefix alignment succeeds. Prompt strings are data, not optimized parameters.

This is a local text-generator parameter-learning interface. It is not joint controller/generator training, an independent semantic qualification, a four-arm result, or a production claim. A one-source update may verify gradients, parameter hashes and checkpoint reload; it cannot establish generalization. The current real-output input/response intervention diagnosis must pass before a four-arm efficacy run is admitted. Parameter learning cannot repair that evidence gap by memorizing one answer.

## Frozen training data

Provide a separately retained SHA-256 of the UTF-8 JSON manifest. Image paths are relative to this manifest, or absolute. Targets are training-only; they must never enter controller views or evaluation prompts.

```json
{
  "schema": "hepta.real-adapter-training-data.v1",
  "role": "training_only",
  "examples": [{
    "source_id": "original-source-001",
    "image_path": "inputs/source-001.png",
    "image_sha256": "REPLACE_WITH_ACTUAL_SHA256",
    "instruction": "Explain the visible object and its position.",
    "target": "A reviewed training-only answer grounded in this source."
  }]
}
```

Duplicate source IDs or identical image bytes are rejected. Repeated optimizer steps are exposures, not new independent sources. The manifest author must still group crops, re-encodings and variants by their underlying source, and separate training, validation and evaluation sources before training; byte hashes alone do not certify semantic independence.

## Execute and reload

```bash
python -m experiments.multimodal_output_portfolio.joint_hepta_20261029.v3.decision_audit.train_adapter \
  --models /tmp/dual-models --manifest /tmp/train.json --output /tmp/adapter-run \
  --source-sha EXACT_40_HEX_SOURCE_COMMIT --manifest-sha256 FROZEN_MANIFEST_SHA256 \
  --seed 17 --rank 4 --steps 4 --learning-rate 0.001 \
  --max-answer-tokens 96 --threads 2 --cpu-budget 600 --wall-budget 600
```

Output includes `adapter.safetensors`, `report.json`, `events.jsonl`, and `cost_receipt.json`. A non-completed run exits nonzero. Reports bind source code, data manifest, seed, requested/completed updates, distinct observed training sources, before/after parameter hashes, changed parameter counts, gradients, and resource allowances. Unchanged or nonfinite updates cannot count as successful training.

`load_adapter(frozen_model, checkpoint_path, expected_checkpoint_sha256)` verifies the exact file and full backbone parameter fingerprint, then returns `(adapter, hook_handle)` for inference. Call `hook_handle.remove()` before replacement; loading another model family discards the VLM instance, so a future backend must reattach on each VLM reload. No published backend is silently modified. Safetensors loading uses no pickle or remote model code. Successful training also replays the final training input through the trained and freshly reloaded hooks, requiring identical logits and reporting their hashes/max difference; both actual forwards and reload hashing are charged. This repeated-input probe is not evaluation data.

## Costs and interpretation

All attempted updates, model loading, full before/after parameter hashing, checkpoint writing, failures, and report writing have exclusive CPU/wall intervals. The final meter journal/receipt write and external process startup remain explicit outer overhead. A wrapper must close that outer scope before claiming end-to-end net utility; unknown costs are not zero. Training costs remain separate from inference costs and are not silently amortized.

CPU/wall allowances are checked at operation boundaries, not preemptive hard deadlines. A failure or timeout retains attempted-step and cost records. No new holdout, independent semantic score, uncertainty claim, image-generator adaptation, or joint-training interaction is established by this module. Behavioral tests use a tiny neural stand-in; actual pretrained-update evidence requires a separate pinned execution receipt.
