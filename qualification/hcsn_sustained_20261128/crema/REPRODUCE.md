# Reproduce the six-layer CREMA-D experiments

Both runners verify the original pretrained-free inputs before constructing the network. Use the archived `billion_recovery/original/scripts/encoder.py` and `hcsn_temporal.py` as `PARENT/src/encoder.py` and `PARENT/src/hcsn_temporal.py`. Place `crema/src/law4.npz` alongside them. Copy the prepared CREMA-D array to `PARENT/data/data.npz`. The on-host study root is recorded in each execution receipt. The data identity is SHA-256 `18423277257e2e487521d83a8c116bc7cf5599411f4ff769e569bd849beae6ad`; this bundle contains metadata, labels, the aligned audiovisual features and the common text gallery. The scripts abort if any of the four digests differs. The original measured runs used one CPU thread, Python with NumPy and PyTorch 2.13.0+rocm10.0.0 in CPU mode.

From the repository's `qualification/hcsn_sustained_20261128` folder, run each study in its own output directory. The sustained study requires at least ten and a half hours of actual optimizer time plus I/O and evaluation. An existing compatible study directory resumes its tracked checkpoints.

```bash
python crema/direct.py "$PARENT" "$EDIT_OUT"
python crema/study.py "$PARENT" "$SUSTAINED_OUT"
```

The first command writes all 27 candidate patches, seals them before scoring held-out actors and writes one score array per candidate. The second command writes the optimizer and RNG states at interval, then seals one selected checkpoint per condition. Full raw score arrays and selected weights are archived together in the study's results branch. The source branch contains the score summaries and independent verifiers. The figure in the Chinese overview can be regenerated with `python paper/plot_channels.py` beside its literature reference implementation.
