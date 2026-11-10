# Independent full-D replay of six original HCSN best checkpoints

All six fresh full-development forwards reproduced their original best-epoch confusion matrices exactly. The largest scalar metric difference was 2.220446049250313e-16, below the frozen 2e-12 gate. The original six fits remain `budget_exhausted`, with training adequacy false. This replay does not establish sufficient training, held-out E confirmation, numerical qualification, or an architectural benefit.

## Method and source identity

The plan and 13-file program were frozen before accessing the six real checkpoints. Both local and exact-native-runtime synthetic validations passed 16 tests. The replay used the actual v8 source, native Torch 2.8.0+cu128, immutable construction configuration, CPU FP64, one thread, and the original full batch-32 evaluation layout. Each of 128 D windows was consumed in manifest order, yielding 31,952 labelled events per fit. Best selection used the first strict maximum in the original epoch history; last checkpoints were not substituted. Budget reports legitimately omit selected-development logits, so comparison is against the bound original best-epoch metrics and confusion matrix.

The independent NumPy calculation recomputed accuracy, macro F1, balanced accuracy, NLL, both Brier conventions, and 15-bin ECE. Model, frozen common/physical tensors, source, and inputs were checked before and after. There were zero optimizer constructions/restores/steps, training updates, or backward calls. Reading existing optimizer/RNG fields inside a safely loaded checkpoint did not execute optimizer operations. Confirmation E data was not read.

| Fit | Best epoch | Macro F1 | Accuracy | NLL | Full child wall (s) | Exit child CPU (s) |
|---|---:|---:|---:|---:|---:|---:|
| hcsn-s101-lr0.001 | 46 | 0.225177175 | 0.568853280 | 1.320242073 | 120.151566 | 120.082057 |
| hcsn-s101-lr0.003 | 47 | 0.353904163 | 0.674887331 | 1.120953525 | 122.027273 | 121.981396 |
| hcsn-s211-lr0.001 | 45 | 0.244923402 | 0.641368302 | 1.275839875 | 121.693953 | 121.611791 |
| hcsn-s211-lr0.003 | 40 | 0.391093236 | 0.702272158 | 1.017387431 | 121.687339 | 121.661276 |
| hcsn-s307-lr0.001 | 46 | 0.159200225 | 0.570324236 | 1.326726528 | 120.994397 | 120.943719 |
| hcsn-s307-lr0.003 | 43 | 0.327756295 | 0.672039309 | 1.230812132 | 122.439421 | 122.401982 |

All six candidates are retained; these rows do not select a best seed or claim that seed variability measures unseen-subject uncertainty. Original D-based model selection remains development tuning.

## Cost scope

The complete controller process group took 730.308706774 s wall and 735.746561 s waited controller-plus-descendant CPU. The outer bootstrap interval, including native synthetic validation, extraction and replay, was 733.179974144 s after its standard-library imports; its waited children used 739.440259 s CPU, with 0.184126431 s bootstrap own CPU reported separately. These are overlapping measurements and must not be summed. Local synthetic validation was an additional 1.820557447 s full child wall and 1.685351 s CPU. An earlier exploratory validation has no complete process timer and remains explicitly unknown.

Peak per-fit self ru_maxrss was 920,285,184 B; the largest sampled RSS was 921,694,208 B. Both were below the declared 2 GiB gate; these two measurements have different sampling semantics. The replay may overlap the separate numerical audit, so it is not a dedicated-host speed comparison. Energy was not measured.

Publication attempt v1 took 8.536668790 s whole child wall and 3.818212 s waited child-plus-descendant CPU. It successfully sealed the archives but failed on the installed gh version rejecting --slurp; no upload branch was reached. The corrected v2 used the same sealed archive, one upload, and a complete authenticated readback. Its complete child wall was 37.780077072 s and child-plus-descendant CPU 4.05913 s. No model or numerical oracle was rerun for packaging or publication. Transport and unmeasured preparation costs remain outside an exact combined total.

## Evidence and archival boundary

The full archive hcsn-best-full-D-independent-replay-20261110-v1.zip is 19,144,412 B with 254 members, SHA256 ff41e5ef909708a5c2472f6786d0e82b6d69a80d968047de2746bcaf84daaac5. It is asset 732788592 on draft release 440410488. Authenticated full download, ZIP CRC and every member hash passed; anonymous asset API/browser and release requests returned 404, and final metadata still says draft. The release was not published.

The full archive contains complete new logits, labels, episode/position/source-row order, all stage logs and receipts, frozen program and actual loaded source, and the D input bytes. Original model bytes are bound member-by-member to the previously authenticated original HCSN archive rather than duplicated. This handoff includes all 80 small-original members, the exact small ZIP, full-archive member manifest, model bindings, both publication attempts, and result/cost summaries. The separate source artifact itself was not altered.

The original 16,811,170 B controller-only ZIP is preserved on the native host. It was not the uploaded container: all of its directory members are included byte-for-byte in the distinct combined archive. Published archive integrity is evidence of reproducibility, not scientific or CI admission.
