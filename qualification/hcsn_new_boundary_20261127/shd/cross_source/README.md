# Hidden weight editing when only two phases of the default boundary cross a layer

This is a controlled three-domain speech experiment using real recordings and 10 digit identities. Three fresh parent models trained only on FSDD and Arabic. At edit time, 480 GSC digit recordings trained a new domain while 300 FSDD and 440 Arabic examples protected the two old domains. Development included 100/220/240 recordings from 1/22/149 people; official or source-held test included 1,000/2,200/1,200 recordings from 2/22/240 people. Train, development and test participants within each corpus are disjoint. The sources themselves had been used by earlier research; this tests new networks and editors on known panels. The SHD and handwritten UJI studies have separate protocols.

## Model and training

A learned 13x16 matrix acts on six native-derived MFCC frames. At each frame the lower neuron sends a first log barrier, computed from its instantaneous drive plus prior physical feedback, and a second log barrier from the same drive after updating equity and first-hit risk. Both log(B/B0) messages are divided by fixed kappa for numerical scale. Only boundary values cross into the learned 32x16 upper matrix. A and F are internal to the lower cell and feed delayed pressure. Each of the 16 upper receivers has its own physical feedback recurrence and returns A,F per time step to the frozen linear class readout. Within-upper-cell temporal feedback preserves separability across receivers. This two-phase construction is an engineering assumption independently tested here. It is distinct from the SHD/UJI A/F-feature encoders. Removing both interlayer boundary channels leaves exactly 10% recording accuracy in every domain; ordinary communication is necessary in this implementation. Changing lower feedback, removing only one boundary or replacing the physical shape is a separate specificity question. Save and inspect intervention tables in results.json.

The physical table approximates the literal stationary A7 equity and finite first-passage F, with both P and B varying. For three matched parents the matrices and 10-way head were learned jointly with BP. The recorded parent-search times were 5.23/4.89/4.73 s. At editing all tensor values were fixed except the actual upper weight. A ± probe in an input direction simultaneously perturbs all upper neurons, then recomposes each neuron's contributions after all six recurrent time steps. Generalized covariance directions emphasize the new in relation to old source variation. A damped local softmax Gauss–Newton/old-output solve determines weights. Compare ordinary random full-matrix probes, ordinary unit covariance directions, label-shuffle, exact KEEP, same-site Adam and LoRA rank four with identical speakers and true retention controls. The shuffled arm verifies how rarely within-speaker permutations change these sparse GSC labels and uses preregistered group-size-preserving cross-speaker derangement as needed.

Protocol e05c23f0, architecture 179e664f, 3 parents plus 42 actual point/conservative selections frozen at 5bb66786 before computing their cold results. For the original arm named white the later unit-norm operation canceled the attempted whitening scale; interpret the original arm as ordinary PCA directions. WHITENING_CORRECTION.md preserves the finding and an after-test repaired sensitivity. The repaired point selector averaged new GSC +1.76pp, old FSDD +2.30pp and old Arabic -1.53pp. Keep this sensitivity distinct from the primary protected-arm gate.

## Held-out outcomes

All accuracy columns below are three-parent means of equally weighted within-source speaker accuracies. The absolute scale matters: GSC held-out transfer remains under 20% on a ten-way task.

| Point selector | FSDD | Arabic | GSC | Three full edit-search times summed |
|---|---:|---:|---:|---:|
| Exact unchanged parent | 53.17% | 83.50% | 17.59% | No update |
| Generalized, forward-only | 55.77% | 81.76% | 19.62% | 3.52 s |
| Unit PCA, forward-only | 55.60% | 81.62% | 19.94% | 3.62 s |
| Random-direction, forward-only | 54.67% | 82.55% | 18.57% | 3.10 s |
| Same-site Adam | 57.73% | 81.61% | 19.83% | 27.58 s |
| Rank-4 LoRA, same matrix | 54.13% | 83.00% | 18.60% | 29.62 s |

Generalized-minus-KEEP changed GSC by +2.03pp [1.00,3.11] and Arabic by -1.74pp [-2.76,-0.76]; FSDD rose +2.60pp with only two test people. The per-seed GSC gains were 1.95,1.32,2.82pp. In the third seed Arabic lost 2.59pp. None satisfied all three primary per-parent conditions. The conservative generalized selector protected Arabic better at -0.61pp while yielding +1.03pp on GSC; only the third seed passed. Shuffled labels averaged -0.04pp on GSC. The stronger gradient baseline gained 2.24pp on GSC. Confidence intervals pair the same speakers and same fit seeds; FSDD's two-person evidence is particularly limited. Programmatic cohorts, costs, all points, class logits and gate values are provided.

Against the best same-site Adam or LoRA observed development target, protected group secants matched the third seed's two selection targets (1.14 vs 3.72 s for point selection, 1.17 vs 3.46 s for conservative selection). They did not reach the other four targets. Original unit PCA reached one further point-selection target. Timings are single CPU worker wall measurements including search and monitored checkpoints, with imports before common clock, cold verification, data acquisition and shared parent pretraining separately charged. Original documented GSC preparation cost 103.81 s; original FSDD/Arabic 1.41 s; this independent raw reconstruction measured 4.72 s. Compare equal-quality targets without extrapolating unobserved crossings. There is no all-seed quality-matched replacement of BP.

## Reproduction and verification

Use the sibling uji/verify.py for the direct (non-tabulated) NumPy A7 used by core.py and verify_speech.py. Ordinary Python NumPy and SciPy suffice to rescore; original parents and gradient controls used CPU PyTorch. Restore the manifest into this directory and define its data location.

```bash
python restore.py .
export HEPTA_MULTILINGUAL_INPUT="$PWD/data" OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1
python confirm.py
python verify_speech.py
```

For raw-waveform replay run acquire.py data and raw_verify.py. Raw acquisition optionally needs the official 2.43GB GSC tarball and validates SHA. FS examples use the original FSDD repository at 26eb9aaf76e81b692f806f9140c2d2777410d7a1, Arabic MFCCs the Bedda–Hammami UCI release DOI 10.24432/C52C9Q, GSC Warden's Speech Commands v0.02, https://storage.googleapis.com/download.tensorflow.org/data/speech_commands_v0.02.tar.gz. Source authors and applicable corpus licenses are retained via original links/metadata. All selected 3,320 PCM waveforms (FSDD and GSC) were reread; no PCM crossed split boundaries. All 6,180 selected source recordings' 6x13 input frames matched the frozen benchmark arrays element for element. The independent FP64 A7/F implementation recomputed 1,848,000 class scores across all 42 primary selections, all 4,400 cold recordings and all ten classes, verified 126 metrics, maximum absolute deviation 0.000101, zero changed labels. Content hashes, original split identities, summaries and logits are included. Adjacent package restore can reconstruct the original 145 logical payloads, including the separate corrected-control results.
