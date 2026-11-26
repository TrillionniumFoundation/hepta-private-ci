# Physical QVI edits for paid sensor features

A cost edit changes the original SmallHCSN sender's threshold. In a real smartphone activity recording, a free expert uses one acceleration axis; the paid expert uses all supplied features. Compare correctness minus the declared acquisition tariff. The tariffs are counterfactual and financial or energy costs were not measured. HCSN is the purchase policy's one-step gate; the two activity classifiers are supervised ridge experts.

## UCI HAR

The frozen train/candidate/development/confirmation groups contain 9/6/6/9 unique people. They cover 2,871/2,195/2,286/2,947 windows. No held-out subject appears in any fit. The test is held out for this experiment; this is an existing public cohort.

| Selected arm | Held-out new utility | Paired gain vs KEEP | 95% person-bootstrap gain | Worst old-person utility change | Pass |
|---|---:|---:|---:|---:|---|
| KEEP | .817014 | .000000 | [0,0] | .000000 | Reference |
| Exact scalar cost edit | .823478 | +.006464 | [−.001682,+.015855] | −.031291 | No |
| Same scalar BP | .822914 | +.005900 | [−.001146,+.014208] | −.026821 | No |
| Wider BP | .819271 | +.002258 | [−.005772,+.011052] | −.059722 | No |
| Ridge purchase readout | .819974 | +.002960 | [−.004969,+.011810] | −.057812 | No |

All four dev-selected edits were deployed for evaluation. Only the two scalar edits meet the test's worst-person old-loss bound (.05). All four intervals cross zero, so none passes the prespecified full gate. The free expert had .427850 accuracy; the paid expert .919870, so always buying at the new price yields .819870 utility. The incumbent already bought on .910978 of windows. Perfect information would yield .892898. The 36 fixed original-module-forward checks per selected physical arm agree with the reduced decisions. These checks are nested in the cohort and are not independent participants. The common model has one sender's local free boundary and an engineered input observation level. The online decision does not require running all eight cells or training a sequence encoder. A conventional sorted threshold can exploit the scalar monotonicity too.

## Reproduce

Check out TrillionniumFoundation/hepta-private-ci at the commit in SOURCE.json, put that root on PYTHONPATH, and install NumPy and PyTorch. The latched environment was NumPy 2.5.2 and Torch 2.13.0+rocm10.0.0 on a CPU. The public data mirror and six immutable Git-blob digests are in SOURCE.json. Download X_train.txt, y_train.txt, subject_train.txt and the three corresponding test files under data/. File bytes are verified before loading. Exact prior source hashes are in SOURCE.json.

```sh
OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1 OMP_NUM_THREADS=1 python har_utility.py train data new-run
OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1 OMP_NUM_THREADS=1 python har_utility.py test data new-run
python verify_har.py new-run
```

The original data are UCI Human Activity Recognition Using Smartphones, DOI 10.24432/C54S4K. The UCI task has six labels. Source discovery and construction of the algorithms, data download, host orchestration, and model source acquisition are outside reported training clocks.

Fifteen fresh local CPU process replays (five arms × three rotated-order rounds) selected identical policies. Median launcher-to-exit for KEEP/exact inverse/same BP/wide BP/ridge was 1.506/1.471/4.743/2.643/6.207 seconds. Individual timings, including substantial shared-host variability, are retained in evidence/cold.json. This includes fresh imports, byte verification, upstream expert fitting, all training and dev selection, and seal equivalence. The separately shared test phase took 0.345 s after imports. It excludes data transfer, program design and production deployment. Equal-quality time for a successful update was not attained by any HAR method.

An external WISDM replication retained 21 independent confirmation participants and 9,086 windows after resolving duplicate subject files before fitting. The three physical edits produced identical always-free actions. Their estimated +.000204 mean gain over KEEP had a paired 95% interval of [−.000514,+.000860]. See [the WISDM cohort, endpoints and cold timings](wisdm/README.md). Verify both archived result sets using `python verify_har.py evidence` and `python verify_har.py wisdm/evidence`; only NumPy and the standard library are needed.
