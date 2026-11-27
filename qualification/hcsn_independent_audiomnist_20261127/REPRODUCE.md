# Reproducing the cross-corpus receiver edit

Run the Python programs from this directory under NumPy and SciPy with one BLAS thread. The recorded environment and threadpool versions are in each parent receipt. The published raw scores and checkpoints support a faster independent check.

```sh
export OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1
python restore_evidence.py evidence
python verify.py evidence/models evidence/cold evidence/SEAL.json independently_recounted.json
cmp independently_recounted.json evidence/RESULTS.json
```

For a fresh training run, check out the FSDD and AudioMNIST repositories at the commits in PROTOCOL.md. AudioMNIST needs only repetitions 0 through 11 of all digits for speaker numbers 01 through 58 at intervals of three. data.py performs resampling and compares PCM at the source sampling rate. The source-hash manifest and ordered split hashes can be inspected in the evidence bundle. The accompanying `catalog_evidence` directory at hepta-private-ci commit b3fdc981568ab9ce122d2fb569372651e0b4b314 includes a 109-member verified archive. Its `restore.py` extracts `paired_catalog/data/law.npz` and the reference `paired_catalog/lawtable.py`.

```sh
python data.py /path/to/FSDD /path/to/AudioMNIST fresh_data
python check_law.py /path/to/paired_catalog/lawtable.py /path/to/paired_catalog/data/law.npz
for seed in 271 577 911; do
    python fit.py fresh_data /path/to/paired_catalog/data/law.npz fresh_models --seed "$seed"
done
python check_law.py /path/to/paired_catalog/lawtable.py /path/to/paired_catalog/data/law.npz > fresh_models/law_check.json
python seal.py fresh_models fresh_data /path/to/paired_catalog/data/law.npz fresh_seal.json
for seed in 271 577 911; do
    python cold.py fresh_models fresh_data /path/to/paired_catalog/data/law.npz fresh_scores fresh_seal.json "$seed" keep 0
    for seconds in 3 15 45; do
        for arm in direct wrong bp lora; do
            python cold.py fresh_models fresh_data /path/to/paired_catalog/data/law.npz fresh_scores fresh_seal.json "$seed" "$arm" "$seconds"
        done
    done
done
python verify.py fresh_models fresh_scores fresh_seal.json fresh_results.json
```

Fits use measured process-time limits. Different hardware can complete different numbers of updates and choose different weights within that limit. To reproduce scores for the originally selected fits, substitute the restored model files and original seal. Rebuilt data arrays should match the file/record manifest. Confirm the recorded file hashes or run the retained score-level verifier.

The direct solver builds input directions from target and parent calibration records. It estimates a downstream Jacobian by paired forward evaluations, solves a ridge problem and tests finite steps through the actual nonlinear cell. The first-order baseline differentiates the complete same-site chain, including the recurrent mean and price feedback, by an exact reverse pass on each bilinear interpolation region. Low-rank Adam trains two rank-three factors in that site. Parent construction fits a supervised ridge readout over random physical hidden features. Every transfer arm keeps this readout fixed.

Scores are retained at full precision for each recording and class. Old and new bootstrap comparisons pair the predictions by speaker and by parent, using the same resampled speakers for every arm. Initiation, feature extraction, parent construction, fitting and test costs have separate clocks. Any ratio of cold times must specify which common preparation and evaluation costs it includes.
