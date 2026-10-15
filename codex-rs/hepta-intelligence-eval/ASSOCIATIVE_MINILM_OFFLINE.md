# Pinned native MiniLM weight execution for associative MemoryCell

**Research only.** This is a bounded, read-only, ASCII-only Python/PyTorch
reference for the exact six-layer `sentence-transformers/all-MiniLM-L6-v2`
weights already staged by the MemoryCell experiments. It is not an installed
Neuron backend, source/fact owner, model selector, inference replacement,
independent evaluation or accepted production memory system.

## Problem addressed

The earlier research branch could train a low-rank `cue -> value` Cell against
source-derived vectors, but the actual frozen pretrained Encoder still required
Transformers/Tokenizers staging in the hosted workflow. A previously staged and
verified 90 MB safetensors snapshot was available on the development host while
those Python packages were unavailable. The new standalone reference executes
**the real pinned tensors** with PyTorch + safetensors without downloading or
executing remote model code. Its evidence is narrowly scoped to local forward
execution until the independent Transformers parity test completes.

The native port:

- Validates exact six-file model inventory, hashes, symlinks and closed-world
  architecture/tensor shapes. `inventory()` can additionally take a trusted
  exact file hash inventory. The resulting encoder identity is compatible with
  the existing `pretrained.file_inventory` and `native.digest` formulation.
- Implements ASCII-only BERT normalization/pre-tokenization, WordPiece and CLS/SEP
  tokens, rejecting Unicode/unknown tokenizer configuration, oversize inputs,
  unsupported model architectures, new model files and silent truncation.
- Executes six actual BERT encoder layers with position/type embeddings,
  attention, feedforward GELU, residuals and LayerNorm. Returns masked mean-pooled
  L2-normalized float32 vectors. Frozen weights never receive gradients.
- Provides a **mandatory** exact-identity, token-ID and vector comparison against
  the actual `pretrained.Encoder` backed by pinned Hugging Face Transformers.
  The CPU comparison rejects differing token sequences, maximum absolute error
  exceeding `2e-5`, or any sample cosine below `0.999999`. These are proposed
  parity tolerances, *not* already observed HF parity evidence.

## Reproduction

Set `HEPTA_ASSOC_ENCODER_DIR` to the unmodified pre-staged `encoder` directory
whose inventory digest is
`5afecdd6098fec07380bc10a30fd8debcffcd147274b3ffd18143f1fa86dc12a`.
Run from the repository root in an environment with CPU torch, safetensors and
NumPy. `PYTHONPATH=scripts/memory_cell` is required:

```bash
HEPTA_ASSOC_ENCODER_DIR=/path/to/pinned/encoder \
PYTHONPATH=scripts/memory_cell \
python -m unittest discover -s scripts/memory_cell \
  -p 'test_associative_minilm_offline.py' -v

PYTHONPATH=scripts/memory_cell python scripts/memory_cell/associative_minilm_probe.py \
  /path/to/pinned/encoder /tmp/empty-new-associative-minilm-probe
```

When Transformers is absent, the local parity test is explicitly **skipped**,
not marked passed. The amended read-only hosted workflow runs the tests and
executes `compare_with_transformers()` after staging the pinned model. Any parity
failure blocks that research job. No implied backend selection follows.

## Observed local native-weight diagnostics (2026-10-15)

The development-host proof used exact six-file inventory `5afecdd...` and local
CPU torch. Five fixed ASCII sentences produced finite unit-normalized vectors
with shape `[5,384]`. Nine dedicated test cases completed, **eight passed and
one HF parity case skipped**. The source-only probe used six synthetic recorded
events from one authored family; it trained a 64-dimensional rank-4 Cell using
160 steps and evaluated new phrasings of **the same sources**:

| Control | Mean latent MSE (lower is better) |
| --- | ---: |
| Untrained parent, 512 trainable parameters | 0.0188857 |
| Updated candidate, 512 trainable parameters | 0.0166581 |
| Source-retaining exact cue-vector 1-nearest neighbor | **0.0000000** |

The source-retaining vector NN **outperformed the parameter model** on this
small fixture; it has all source-derived value vectors available at read time.
This is not an indexed, independently tuned strong RAG baseline and does not
prove strong retrieval's general superiority. MSE is on a source-derived latent
target, not a semantic QA or citation measure. The parametric delta from the
untrained parent is small and on correlated same-source tasks. The full model
file size is counted rather than excluded from storage accounting.

## Explicit non-claims and next experiment

No independent source-family transfer, production citation, real future window,
semantic reader, qualified deletion/unlearning, type split/graph causal gain,
statistically significant improvement, strong tuned RAG victory, independent
acceptance, or production promotion is demonstrated. The native port must not
silently replace the HF Encoder for general Unicode tasks, and unsupported inputs
remain fail closed. Keep the source owner, artifact/rollback authority and
`blocking-ci` unchanged.

Next: require hosted exact token/latent parity; then train and evaluate on
externally admitted independent source families with fixed Reader and cached
BM25+dense/hybrid retrieval at equal lifecycle cost. If the strong source-retaining
controls win, retain them rather than promoting the parameter Cell.
