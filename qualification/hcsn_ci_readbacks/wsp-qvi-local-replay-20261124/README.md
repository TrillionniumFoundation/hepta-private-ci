The complete runnable source and evidence are in [Hepta_QVI_Weight_Edit_Evidence_20261124.zip](Hepta_QVI_Weight_Edit_Evidence_20261124.zip). Extract that archive before following the replay commands below. ZIP SHA-256: `7af73ede04e85de4db714863de083c8057e33e33cbfca10aa6386b4ed1b1b7b6`.

# QVI conditional edit replay and causal controls — 2026-11-24

This small evidence package retains the exact original source, original results, a new single-thread CPU replay, and a controlled diagnostic showing why single-anchor preservation is not global retention. It contains no model promotion or Pocket4 trading-performance claim.

Read `AUDIT_RESULTS_ZH.md` for the six-module mapping and the surrounding Hepta research audit; `FORMULAE_ZH.md` derives the inverse and its limits.

## Results

- Original three-arm replay: unchanged 0.074264405 s, structural edit 0.079543336 s, joint L-BFGS 0.157437582 s, medians including common preparation and validation.
- Direct edit: cost delta 0.019345554018888933; input-bias delta 0.009195251723316866; boundary error 2.22e-16; anchor 49-output maximum change 2.78e-16.
- Extra fixed controls: 21 initial states, eight arms, 49 outputs. Joint direct/BP pass the original target-and-anchor rule; no nonzero arm preserves every grid output. Direct's worst grid change is 0.007229360858953426.
- Independent scalar checks on 168 forward panels: maximum boundary/start/receiver-phase error 5.00e-16.
- The first extra-controls attempt failed only at final JSON serialization of a NumPy bool_. Its source/protocol/failure record are retained. The succeeding attempt changes that serialization and the output directory only.

## Replay

Use a new environment with Python 3.12, NumPy 2.3.5 and SciPy 1.17.0. The recorded CPU framework is Torch 2.10.0+cpu. The framework binaries are not bundled. For example install the CPU wheel from the official CPU index, then install the two recorded scientific packages.

```bash
python -m pip install torch==2.10.0 --index-url https://download.pytorch.org/whl/cpu
python -m pip install numpy==2.3.5 scipy==1.17.0
mkdir fresh-replay
PYTHONPATH="$PWD" OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 python qualification/hcsn_ci_readbacks/qvi-conditional-edit-20261123/compare.py --output fresh-replay/results.json
cp qualification/hcsn_ci_readbacks/qvi-conditional-edit-20261123/protocol.json fresh-replay/
cp qualification/hcsn_ci_readbacks/qvi-conditional-edit-20261123/independent.py fresh-replay/
PYTHONPATH="$PWD" OPENBLAS_NUM_THREADS=1 python fresh-replay/independent.py
```

The `run_replay.py` recording wrapper intentionally refuses to overwrite its fixed `replay_20261124` output. The commands above are the portable fresh-output entry point. `run_ablation.py` similarly refuses to overwrite `ablation_attempt002`; its literal fixed output directory may be changed to a new name for a separately identified replay. Its scientific points and directions must remain unchanged to reproduce the recorded controls. `verify_ablation.py` rechecks the saved controls without importing Torch.

## Provenance and limits

The science source is `610f91087b598656f7f3913e600c705b95bf071f`. `source_provenance.json` records exact Git blob identities and URLs for all 13 upstream files. `MANIFEST.json` binds every shipped member except itself. `replay_20261124/source_freeze.json` is the original local pre-run receipt and retains its historical absolute paths. Do not relabel new timing measurements as that recording.

The two-coordinate goal and anchor were researcher-specified. Extra controls diagnose the already observed candidate; they are not independent task-generalization data. The package excludes Torch installations, caches and compiled bytecode. The surrounding Rust workspace was not built or formatted in this isolated environment; there are no Rust production-source changes, and this package conveys no whole-repository CI qualification.
