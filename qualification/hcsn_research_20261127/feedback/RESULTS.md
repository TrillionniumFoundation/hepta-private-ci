# Centered free-boundary communication with causal next-drift feedback

The matched 48 fits test whether two simultaneous feedback terms improve a network whose senders communicate only their previous endogenous boundary relative to a fixed physical reference. On two real sensor tasks the boundary delivered a highly discriminative signal. At the standard 0.5 decision threshold, the N8 physical models predicted the negative class for every example. Fitting a single threshold on development data recovered much of their classification performance. The dual branch showed no consistent improvement over the same calibrated network with both gains fixed at zero.

## Physical intervention

Model code is based on research snapshot 8b538954e3db0763b9eb24b6159d17b80f286f26. The generator, moving-boundary remap, signed content transport, regenerative stages, QVI, first-hit mass and uniformized time advance remain those of the pinned model. Both new drives use time-t state. One drive uses the active density’s distance from a target under the complement of the discounted hitting transform. The second depresses the next drift in proportion to the preceding step’s first-hit risk. The gain pair takes the values (0,0), (0.6,0), (0,0.6), or (0.6,0.6). These are proposed neural feedback laws. The discounted transform, first-hit probability and the legacy finance paper’s contractual payoff are distinct objects.

Only senders read the original observation, only receivers feed the classifier, and inter-neuron communication transmits the last QVI boundary less its same-neuron stationary reference. The accumulating two-tick control combines information at the slower physical clock. The readout sees the receiver’s five features per unit. The N8 model uses four senders and four receivers. The conventional tanh gate shares the source/receiver separation and slow clock; GRU, LIF and attention use their pinned conventional input pathways.

The causal tests compare against the frozen original with both gains zero. Double-precision output, features and input derivative match exactly for a matched initial state. Silencing boundary messages removes the input derivative. Chunked state continuation agrees with full-sequence evaluation; trace and time-index-specific derivatives are in mechanism_tests.json.

## Prospective primary results

Each entry is mean balanced accuracy / Brier / AUROC over three predetermined seeds. The two sources have fixed splits. The office target is occupancy at the final observation of an eight-minute window. Beijing uses midnight through 07:00 as input and predicts whether 13:00 PM2.5 exceeds 75 micrograms per cubic meter. Beijing training uses six sites through February 2015, development uses two disjoint sites in the following year, and test uses four different sites in the final year. Each source contributes at most six label-independent valid days per month and site.

| Network or active forces | Office, 224 windows / 7 dates | Beijing, 288 windows / 4 sites |
|---|---:|---:|
| No feedback | .500 / .13881 / .93874 | .500 / .23311 / .87721 |
| Restoring only | .500 / .13899 / .93954 | .500 / .23325 / .87826 |
| Risk only | .500 / .13903 / .93412 | .500 / .23317 / .87893 |
| Both | .500 / .13898 / .93500 | .500 / .23315 / .87861 |
| Centered tanh gate | .87634 / .11995 / .97388 | .70250 / .18596 / .80327 |
| GRU | .87270 / .11664 / .96064 | .76551 / .13740 / .90654 |
| Surrogate LIF | .86708 / .09920 / .94544 | .70968 / .16177 / .86783 |
| Causal attention | .90408 / .09228 / .97859 | .79855 / .12982 / .90664 |

Across seeds the dual model’s positive probability on the office data was between .1848 and .2908. Beijing’s range was .3506 to .4343. The ranking still distinguished most positives from negatives. Silencing the delivered boundary makes the dual-model AUROC exactly .5 in all six matched fits. Mean CPU elapsed fit time in the pilot was 17.40 seconds for dual versus .31 for attention on office, and 17.05 versus .45 seconds in Beijing. All models had the same 128-step optimizer budget, labels, loss and development checkpoints. Capacity and CPU timing differ by model; primary fit timing excludes data preparation and imports. The threshold, comparison and choice rules in protocol.json were frozen before opening primary test splits. Primary_summary.json includes per-seed scores, probability ranges and paired descriptive intervals by observed day or site. The predeclared joint BA and Brier advantage gate failed on both tasks.

## Follow-up on the decision threshold

After inspecting the primary predictions, two pre-specified calibration rules were separately fitted on the original development data of all 48 sealed models. One selects the probability threshold maximizing development balanced accuracy. One fits a monotone regularized two-parameter logistic calibration. All parameters were sealed before replaying the same held-out examples. The result is a mechanism diagnosis on reused domains.

| Intervention | Office dual | Office zero | Beijing dual | Beijing zero |
|---|---:|---:|---:|---:|
| Threshold selected on dev, BA | .8990 | .9000 | .7540 | .7568 |
| Logistic calibration, BA / Brier | .8904 / .1239 | .8894 / .1238 | .7619 / .1479 | .7562 / .1487 |

The calibration effect is much larger than the effect of adding either physical feedback term. With the same logistic calibration, attention obtains .9109 / .0845 on office and .7899 / .1314 in Beijing. Under development-selected thresholds, the simple centered gate reaches .9350 on office, while the GRU reaches .8181 in Beijing.

## Reproducibility

Place the source checkout on PYTHONPATH and run in this directory. Office source files datatraining.txt, datatest.txt and datatest2.txt must match the three hashes in the pinned stream loader. Public data are UCI 357 (Candanedo, 2016, DOI 10.24432/C5X01N) and UCI 501 (Chen, 2017, DOI 10.24432/C5RK5G), both licensed CC BY 4.0. The script expects the official Beijing ZIP under the name beijing.zip. Its SHA-256 is b04da438b2f331ac0ffd45aebdfec0d20d2367feb5f6948c4b1f7ce1191e33c4. The host used torch 2.15.0+cpu. The primary fit intentionally skips already completed slots only after checking their selected-weight hashes.

```bash
export OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1
python verify_mechanism.py
python campaign.py fit --office /data/office --beijing /data/beijing --out results
python campaign.py confirm --office /data/office --beijing /data/beijing --out results
python analyze.py
python calibration.py /data/office /data/beijing
```

To audit the matched inference without training, the three primary ZIPs provide selected weight tensors, row-level predictions, fits and the full roster seal. Their paths are relative to results/. Extract them there. Run analyze.py to recompute all primary metrics. Development-selected calibration decisions and both sets of held-out row predictions are contained in calibration_records.zip. Per-seed repeats on the same 7 days and 4 stations do not multiply the effective number of domains.

The solver qualification in boundary_variant.py and root_verification.py covers the pinned affine regenerative QVI. It reduces the scalar smooth-pasting equation to a dimensionless monotone root with a Lambert-W representation and an explicit derivative for the three declared control inputs. On 7,011 calibration-grid points, root and derivative discrepancies were at numerical precision. Independent-difference and timing records are in root_verification.json. Kernel timings and small end-to-end pilots use different scopes. They do not establish a whole-network or foundation-model training speed advantage.
