# Shared gate direct CLI failure and correction

2026-10-14. Original source b531b26f92286afc863fc74338b733ebc0a2906b.
Run38522429524/job115714978736 completed FAILURE. Complete decoded logs show
217/217 tests passed, zero skipped (34 gate +54 protocol +14 matrix +29 native
+17 Encoder +34 SELECT +19 supplementary +16 TRAIN-pair tests).

The actual command then failed at import time with
`ModuleNotFoundError: No module named 'experiments'`, before creating the study
output, loading a pretrained model or fitting any real Head. Input archives had
already been downloaded and their external hashes verified; those costs remain.
Artifact11876100386: GitHub reported1478115 bytes/491 files,
SHA256 3e9644ec39f85549a3c8d435ce35397819d98fcd2443745d2b3270a750fe5c80.
This metadata/log observation is not a local output-archive rehash.

`python -m unittest discover` from the root exposes the repository on sys.path;
`python scripts/memory_cell/shared_question_gate_trial.py` exposes the script's
directory instead. Gate imports experiments before the native worker's own
repository bootstrap. The correction adds the SAME source-file-relative root
bootstrap already used in five_causal_native.py, before shared execution imports.
No candidate, architecture, dataset, target, loss, budget, seed, scientific plan,
threshold, tokenizer or source body changes.

Four new subprocess tests run the actual CLI --help from the root and from an
unrelated directory with inherited PYTHONPATH removed, verify missing arguments
reach argparse rather than import failure, and ensure a foreign working directory
cannot supply the experiments module. They do not download or load any model.
The workflow now requires these tests before downloading the full model archive.

Initial correction publication: local container and Python probes failed with
ClientError. New tests and the corrected real-model execution are submitted, not
claimed passing. The original failed run remains failed; its mechanism tests
are not model efficacy. No duplicate Reader training/recovery is triggered.
