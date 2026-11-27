# Raw RSICD captioning through six He–Xiong population layers

The 11,101,984-parameter literal model receives pixels and a causal prefix of original-author words. Each block handles temporal dependence with sixteen finite populations. Each group carries four live masses, one refractory mass, its previous boundary and prices, and a gated feature vector. The feedforward sublayer, normalization and residual maps act independently at each token. The image patch projection and the tied vocabulary output also have no attention or temporal mixer. A same-width causal attention control with an internal 208-dimensional projection has 10,860,512 parameters. The constructor and training protocol use RSICD's previously evaluated split. Short paired retrieval scores belong to a separate task.

The shift of the log boundary changes the distance of each incoming live atom. Bin-integrated killed-transition probabilities move survivors into four output bins and first-hitting probabilities move the absorbed mass into a one-step refractory compartment. The previous refractory mass returns to the reset bin. Endpoint bin masses weight the analytic equity and the separately derived monetary rollover-loss functions. Their dependence on the bounded principal control is affine at fixed grid margin. Both prices affect subsequent boundary control and current emitted content. Silencing the explicit inter-layer wire leaves ordinary residual content intact. Removing a price removes its feedback and emitted content while preserving the first-passage and mass updates.

The four-atom and one-step refractory descriptions are finite modeling choices. Qualification checks independent price and wire interventions, finite gradients, causal prefixes, mass conservation, tabulation and sensitivity to twelve bins. Six-layer residual, random initial weights and gradient training remain part of this experiment. A future-independent NLL requires the prefix mask and the EOS censoring in `prepare.py`.

## Reproduction

Use the checked-in b3fdc981568ab9ce122d2fb569372651e0b4b314 `qualification/hcsn_continuous_20261127/core` directory as `HCSN_CORE`. Build canonical RSICD inputs with the sibling `qualification/hcsn_rsicd_20261127/fetch.py` and `prepare.py`, using the pinned original-author JSON and pixel parquet files. Set `FULLSTACK_DATA` to the target experiment directory and point `PYTHON` at the one-thread Torch 2.8.0+cpu environment. The command examples assume these environment variables and an available frozen CPU number through `CORE`.

```bash
source env.sh
"$PYTHON" prepare.py "$HCSN_CATALOG_DATA" "$RSICD_RAW" "$FULLSTACK_DATA"
"$PYTHON" build_law.py "$FULLSTACK_DATA"
taskset -c "$CORE" "$PYTHON" qualify.py
taskset -c "$CORE" "$PYTHON" -u run.py
"$PYTHON" summarize.py "$FULLSTACK_DATA"
```

`run.py` requires all 24 development fits to finish before creating the joint selection seal or starting held-out scoring. Timed eligibility can vary between machines. `replay_weights.py ARM SEED STEPS OUTPUT_DIR --expected SHA256` recovers a particular original state by running its exact update count from its original seed. It validates the original PyTorch archive in the specified numerical environment. `pack_weights.py DATA_DIR SEED` takes the 300-CPU-second winner from each of eight arms for a seed, creates a lossless ZIP, opens it again and verifies every state checksum. Raw paired held-out NLL sums and true token counts suffice to reproduce all published endpoints independently.
