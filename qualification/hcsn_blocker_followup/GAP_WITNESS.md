# Counterfactual witnesses for the missing audio prefix

The original Commons piano performance has a hole in the first scheduled window. At 44,100 Hz the rounded query begins at sample 32,222 and the first available decoded sample arrives at 32,634. The missing interval is exactly 412 samples (9.3424 ms). Its sound cannot be recovered from this file. [Original Commons source and license](https://commons.wikimedia.org/w/index.php?oldid=1298336907)

We replayed all 66 previously sealed READ/noREAD arms under 41 bounded mono completions of those 412 samples, holding the recorded suffix, images, physical frame times, labels, task price, weights and selected heads fixed within each timing convention. These counterfactuals include silence, a ramp, bounded pseudorandom noise, tones and deterministic tone mixtures. A difference between two completions demonstrates ambiguity within this digital-signal class. Agreement across 41 candidates leaves other signals untested.

| Alignment fixed within every comparison | Arms changing first action and utility |
|---|---:|
| Anchor at first observed sample, retain decoded sample order | 25 / 66 |
| Literal packet timestamps, earliest value at overlaps | 23 / 66 |
| Literal packet timestamps, latest value at overlaps | 23 / 66 |

The container's audio timestamps have 1 ms precision. Within the query, presentation positions differ from the contiguous sample-order convention by up to 16 samples (0.363 ms). The same 23 arms changed under all three conventions. The external task boundary with seed 284729, for both KEEP and BP, accounts for the other two in the anchored convention. Every completion yielded a correct first-prefix terminal response. The ambiguity was whether to STOP for utility 1 or purchase the correct video answer for utility 0.70. These candidates produced no WAIT and changed none of the 33 independently refitted noREAD arms.

Reproduce from the main repository root with the original intervention evidence and physical dependencies. The script checks the original Commons SHA-1, complete semantic camera SHA-256, previous frontend and model seals. It opens an exclusively new output file and does not alter any observation or the released finite-roster bounds. The JSON contains suffix/frame checksums and the first counterfactual witness for every distinct terminal outcome, per arm and alignment.

```bash
mkdir -p gap-replay
for part in qualification/hcsn_intervention_value/evidence/records-*.zip; do unzip -oq "$part" -d gap-replay; done
curl -L https://upload.wikimedia.org/wikipedia/commons/8/87/Pianludado_en_librovendejo_en_Erevano.webm -o gap-replay/112833470.webm
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 python -m qualification.hcsn_blocker_followup.gap_witness \
  gap-replay/media/recording_roster/test.json gap-replay/112833470.webm gap-replay/semantic/test.npz \
  gap-replay/primary/discovery gap-replay/primary/policies gap-replay/result.json
```

[Machine-readable witnesses](evidence/gap_witness.json)
