# V11 fresh content memory: executed results and limits

## Finding

Actual attention-internal Transformer adapters learned the new 16-address
memory and answered every known held wording in all three training seeds.
Disabling those adapters while keeping the trained head caused a large loss
of recall. This establishes that the implementation trains and uses internal
model parameters; it is not an affine head presented as Transformer tuning.

It does **not** establish a better general memory system or a compression win.
The explicit identifier registry already answered every known query, rejected
all eight unknown/ambiguous requests, and needs no neural fit. The nearest
training-embedding control also recovered every known answer before its
confidence gate. Most importantly, the calibrated adapter rejected **every
known held request in two of the three seeds**. Perfect raw recall is not
equivalent to useful calibrated access.

The experiment uses one newly authored corpus, with dataset seed `1943119`,
and three model initialization/minibatch-schedule seeds. These are not three
independent datasets. All claims below are restricted to this finite corpus.

## Frozen design and evidence

[PROTOCOL_content.json](PROTOCOL_content.json) was written before the formal
run. The controller froze its bytes, [content_experiment.py](content_experiment.py),
[models.py](models.py), the held template file, and the local model identity
before preparing data or fitting an arm. Every worker checked these source
hashes again. The run has 15 successful subprocess receipts: preparation,
12 fits, calibration, and evaluation. No worker failed or was replaced.

Each seed uses the same `256 × 16` schedule for all four learned arms:
4,096 presentations of the same 48 training queries and their 16 source facts.
All four schedules match within each seed. Architecture sizes and actual
compute costs differ; equal presentations do not mean equal FLOPs or time.

The new encoder is the full-precision Torch version of
`sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2`, revision
`e8f8c211226b894fcb81acc59f3b34ba3efd5f42`. All feature arms use its normalized
masked-mean embeddings. The internal adapter modifies query and value
projections in its attention layers, with rank 4, and also trains its output
head. The adapter head initially matches the corresponding linear arm.
This Torch profile is distinct from the quantized ONNX profile used by V10;
the separate V10 diagnostic uses the original cached features instead.

The fitting children read training rows only. A separate calibration process
selects thresholds with zero accepted unknown/ambiguous calibration requests,
maximizing correct known acceptance and then preferring the higher threshold.
Held wording is generated only after all fit and calibration children exit.
A fresh evaluation process loads saved checkpoints and the frozen thresholds.

### Identity

| Item | SHA-256 |
| --- | --- |
| Local pre-run `FREEZE.json` | `cda1ef6cc6ac1a4e036ad42b7b113a4eb200e64b14b6f27c7be8c5f078aeedf3` |
| Frozen `models.py` | `5cced6633c73ff4a0b32a3817b43116c37f2f65f9d1ad2fddc7d8f917a9ca802` |
| Frozen `content_experiment.py` | `9ab793c9c427d90cf0e3851c06201287344de867f4b4c33ffd06e9ade8b0cac4` |
| Frozen content protocol | `6b70010649267f60006dcfb8db6b31ab6c2220ac88e14aa6cbb963b8100e53a2` |
| Base-model identity manifest | `28b1a3b662298722d12f5be943b21c00920f8584ea5a02eea4fc86bd4d794fa1` |
| Complete content evidence archive | `f3a387a65f8feb774b5e9403a80c35d9711a45791ec3479161ee2b296c749649` |

`FREEZE.json` is a local commitment made before fitting, not a claim of prior
remote publication. `EXECUTED_SOURCE/` contains the exact source bytes copied
after the run and verified against that commitment. This report and
`POSTRUN_SUMMARY.json` are post-run interpretation; they were not used to
choose a model, threshold, training budget, or test partition. A later GitHub
commit records publication identity and does not retroactively change the
time or scope of the local freeze.

## Raw recall, accepted access, and false acceptance

Canonical recall is a read at the stored canonical wording, out of 16 facts.
Held raw recall ignores the selected service confidence threshold, out of
48 known queries. **Accessible correct** counts a request only when it is
both accepted by the calibrated threshold and exactly correct. Known accepted
is also shown, so a wrong accepted answer cannot disappear into a coverage
number. The final column counts accepted requests among four unknown
identifiers and four ambiguous two-identifier queries.

| Model | Seed | Canonical exact / 16 | Held raw exact / 48 | Accessible correct / 48 | Known accepted / 48 | Unknown/ambiguous accepted / 8 | Threshold |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Linear | 29101 | 12 | 23 | 11 | 11 | 0 | 0.5 |
| Linear | 29102 | 11 | 25 | 10 | 11 | 1 | 0.5 |
| Linear | 29103 | 12 | 24 | 9 | 10 | 0 | 0.5 |
| Nonlinear MLP | 29101 | 16 | 46 | 28 | 28 | 1 | 2.0 |
| Nonlinear MLP | 29102 | 16 | 47 | 29 | 29 | 2 | 2.0 |
| Nonlinear MLP | 29103 | 16 | 46 | 32 | 32 | 3 | 2.0 |
| Soft associative module | 29101 | 3 | 9 | 6 | 6 | 0 | 0.5 |
| Soft associative module | 29102 | 2 | 6 | 3 | 3 | 1 | 1.0 |
| Soft associative module | 29103 | 1 | 5 | 3 | 3 | 0 | 0.5 |
| Internal Transformer adapter | 29101 | 16 | 48 | **0** | **0** | 0 | **32.0** |
| Internal Transformer adapter | 29102 | 16 | 48 | **0** | **0** | 0 | **32.0** |
| Internal Transformer adapter | 29103 | 16 | 48 | 48 | 48 | 0 | 2.0 |

For the two reject-all adapter seeds, accepted-known precision is undefined
and remains JSON `null`; it is not reported as 100%. The third seed accepts
all known held queries with no false accepts among these eight negative
queries. Eight negative queries do not establish a general false-accept bound.
The MLP's six false accepts across the three seed evaluations also show that
zero false accepts on calibration did not transfer reliably to held wording.

### Strong controls

These deterministic controls are evaluated once on the same fixed corpus;
their outcomes are not multiplied by three to manufacture independent trials.

| Control | Held raw exact / 48 | Accessible correct / 48 | Known accepted / 48 | Unknown/ambiguous accepted / 8 | Threshold |
| --- | ---: | ---: | ---: | ---: | ---: |
| Explicit identifier registry | 48 | 48 | 48 | 0 | 0.5 |
| Nearest training embedding | 48 | 0 | 0 | 0 | 1.0 |
| Closed-form affine pseudoinverse | 5 | 0 | 0 | 0 | 32.0 |

Every query explicitly carries an identifier. The registry performs unique
literal binding against the source keys and returns their stored values; it
does not have a hidden gold address. Its result is a strong comparator for
this task, not evidence of unrestricted language understanding. The nearest
control uses all training wordings and values, then applies its own
calibration-selected similarity threshold. The pseudoinverse fits the same
training features to signed margin-8 labels and keeps its negative held
result. No failed control is removed from the comparison.

## Adapter intervention

The intervention disables all internal A/B updates at inference while leaving
the final trained head and base encoder unchanged. It does not re-fit or
recalibrate the ablated model.

| Seed | Adapter enabled: canonical / 16 | Disabled: canonical / 16 | Enabled: held raw / 48 | Disabled: held raw / 48 | Maximum held logit change |
| --- | ---: | ---: | ---: | ---: | ---: |
| 29101 | 16 | 1 | 48 | 1 | 9.038089 |
| 29102 | 16 | 3 | 48 | 5 | 8.954421 |
| 29103 | 16 | 2 | 48 | 0 | 8.120187 |

The fit receipts record gradients and parameter-change norms for every
trainable tensor. The intervention establishes dependence on internal
adaptation in the trained model. It does not by itself establish the optimality
of this architecture or replace the independently trained linear and MLP
controls. The soft associative implementation is one fixed-budget trainable
key/value design; its poor result does not reject all associative memory
architectures.

## Storage and compute accounting

| Arm | Trainable scalars | Raw FP32 parameter bytes | Saved `weights.pt` bytes, per seed | Complete mutable checkpoint bytes, per seed | Observed fit wall seconds, three seeds |
| --- | ---: | ---: | ---: | ---: | --- |
| Linear | 4,620 | 18,480 | 20,261 | 22,148 | 5.079; 5.117; 5.312 |
| MLP | 50,828 | 203,312 | 205,469 | 207,354 | 4.849; 4.513; 4.499 |
| Associative | 6,349 | 25,396 | 27,549 | 29,441 | 4.397; 3.911; 4.206 |
| Internal adapter + head | 78,348 | 313,392 | 329,421 | 332,626 | 100.146; 75.186; 67.344 |

The adapter's fit CPU times were 159.560, 137.669, and 133.048 seconds.
These are fit-call measurements, not isolated kernel benchmarks. Full worker
startup, model loading, calibration, encoding, and evaluation are separately
retained in `PROCESSES.json` and `*.RESOURCE.json`. The controller's complete
15-worker execution took 445.236 seconds in this environment.

Additional costs are retained explicitly:

- Shared base-model and tokenizer assets: **484,793,822 bytes**, counted once
  as shared assets, not silently omitted and not copied into every cell.
- `records.json`: 4,708 bytes. Training, calibration, and held query JSON:
  15,025, 12,617, and 17,578 bytes. These include provenance/evaluation metadata;
  they are not all required in a minimal serving registry.
- Frozen feature caches: 68,562 + 57,246 + 80,009 = **205,817 compressed
  bytes**; their decoded float32 arrays occupy 221,184 bytes. Training features
  are 48×384, calibration 40×384, and held 56×384.
- Each saved training schedule: 32,896 bytes; 12 copies total 394,752 bytes.
  They are retained execution evidence, not deployed model parameters.
- Closed-form affine control: 37,088 bytes for its `.npy` coefficient file.
- Complete sealed content evidence: **4,404,903 uncompressed bytes** and
  **2,037,732 bytes** in `v11-content-formal-01.tar.xz`. This includes all arms,
  predictions, copies of the executed source, and retained audit materials.

This experiment does not persist Adam state. Adam's two FP32 moment arrays
alone require at least `8 × trainable_scalars` bytes while fitting; gradients,
initial-parameter copies used for the change receipt, step counters,
activations, token batches, allocator state, and the shared model are
additional. That formula is an accounting lower bound, not a separately
measured optimizer allocation. The process RSS receipts include runtime and
process-launch effects and cannot be interpreted as pure model tensor memory.
Exact mid-fit continuation is not provided by these content checkpoints;
reproduce the declared fit from its saved schedule instead. The separate
maintenance experiment has its own optimizer persistence contract.

Feature-based prediction timers receive precomputed embeddings; the adapter
reader executes the encoder and additionally performs the ablation. Therefore
`read_wall_seconds_including_load_and_ablation` is not an apples-to-apples
end-to-end latency comparison. The encoder and cache costs must accompany any
serving comparison. Installation cost, cloud scheduling effects, energy,
distributed transport, and a production deployment lifecycle were not measured
here. No storage-compression, latency, or full-cost superiority claim is made.

## Reproduction

The recorded environment used Python 3.12, NumPy 2.3.5, Torch 2.14.1+cpu,
Transformers 4.57.6, and tokenizers 0.22.2. Model loading is local-only and
verifies every listed model/tokenizer asset against `MODEL_IDENTITY.json`;
the full manifest bytes must also match the frozen SHA-256 above. The base
weights are shared input assets, not included in the result archive.

On the original prepared environment, use a new output directory:

```bash
v11_python=/workspace/scratch/fa15dc544533/memory-v11-venv/bin/python
v11_encoder=/workspace/scratch/fa15dc544533/models/minilm-pinned
v11_source=/workspace/scratch/fa15dc544533/hepta-memory-v11/qualification/memory-cell-v11
v11_output=/workspace/scratch/fa15dc544533/v11-content-reproduction-01
OPENBLAS_NUM_THREADS=2 OMP_NUM_THREADS=2 MKL_NUM_THREADS=2 \
  "$v11_python" "$v11_source/content_experiment.py" run \
  --encoder "$v11_encoder" --output "$v11_output"
```

The command refuses to reuse an existing output directory. For a later source
checkout, restore the archive, copy its `EXECUTED_SOURCE/` files into a new
isolated directory, set `v11_source` to that directory, and run the same
command with a compatible frozen Python environment and the authenticated
base-model directory. `FREEZE.json` binds exact executed source, while the
later repository report can evolve without changing old results.

The original archive is
`/workspace/scratch/fa15dc544533/v11-content-formal-01.tar.xz`. Its checksum
above authenticates the complete byte stream, including `FINAL_ARTIFACTS.json`.
The same immutable bytes are available from the checked-in
[content evidence package](evidence/archives/content-v11/README.md), whose
restore command verifies every chunk and retained file.
`FINAL_ARTIFACTS.json` inventories all retained members except itself. The earlier
`ARTIFACTS.json` explicitly predates final run receipts/source copies and is
not used as an exhaustive final byte count.

## Remaining research claims

This run closes the implementation question of whether a genuine internal
adapter can acquire and use fresh finite content. It leaves three substantive
questions open: reliable calibrated access across seeds and wording,
advantage over strong exact/retrieval controls under complete cost accounting,
and transfer beyond a 16-address authored corpus. The V10 pseudoinverse
diagnostic remains retrospective evidence about expressivity and optimization;
it is not a new V10 qualification or proof that V11 scales to 128 addresses.
