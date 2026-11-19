# P3 E14 exact original four-archive negative-control replay

**Research-only / Draft / DENY_ALL.** Additive child of original genuine-human E14 [PR #2178](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/2178), frozen initial source `accc43e06cb2a860eecaf15aee93a1be408d2499`. Original E14 calculations, policy, real human-label scorer, source/model weights, contracts and production runtime are **unchanged**.

## Actual evidence downloaded and checked (2026-10-15)

Original completed Actions run [38679381761](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/38679381761) reported two genuine label-blind + two genuine independent human-score artifacts. The independently reopened outer ZIP SHA256s and original artifact IDs are:

| Role | Artifact ID | SHA256 of **complete original ZIP** |
| --- | ---: | --- |
| Source-head blind, 33 predictions | 11947743374 | `e8cc5bfad419de8976c467df676bc20f91f6a4d37af376b55bfdb58a8ab43a81` |
| Synthetic-merge blind | 11947373682 | `e143cdc891bfefb93df6b25fe12d5bdb73084531b419a0a4e9b8dde2531f5146` |
| Source-head independent original-human score | 11946818427 | `d7ee5bc9d8f4a3f2323dc83dc6e94fee31db2966a610f3af4ede148562506908` |
| Synthetic-merge independent original-human score | 11947358809 | `efd3525b6c412b1681333b1f1185a6879973ae93340b12f786139eb45a3ff0f4` |

The original pretrained source archive itself is separately SHA-pinned as `1a9b485b6b1ee28c952934069b2cd4d765a17742655f3f3cb3339d3ca672ad17`; E14 **does not retrain** or re-execute that pretrained model.

`archived_e14_independent.py` is independent standard-library original-artifact analysis, not an import of the E14 producer or its original score. It checks source SHA, two complete 33-row/source-group policy traces, every recorded exact rational residual, original per-case numerical CPU, identical nonvolatile model outputs and policy routes, and both independently scored original-human aggregates. No original raw logits/text/media or human label rows are committed.

## Observed retrospective original-human result, **not a prospective causal win**

| Fixed original E14 arm | Correct/33 | Brier | Incremental E14 original numeric CPU |
| --- | ---: | ---: | --- |
| Cheap one-map route | 15 | 0.6127287813 | 7,848,257 ns (merge) / 11,006,064 ns (source-head) |
| Full E12 FBSDE route | 15 | 0.6233731355 | 51,814,496 ns (merge) / 71,045,175 ns (source-head) |

The actual case-by-case sum gives full-to-cheap CPU ratios of **6.6020** (synthetic-merge) and **6.4551** (source-head), using 33 dependent candidate alternatives from **four original passages/eight questions**. All six differing cheap/FBSDE routing decisions have identical original source/merge policy traces. The original E14 numerical stage is descriptively worse in cost and Brier without improving accuracy in this small historical panel.

These timing samples count **the reported local Python numerical control, not original Encoder/Reader loads, context assembly, verified execution, provider latency, training, energy, full serving p95/p99 or effect authority**. Four passages, not 33 independent tasks; two repeat runs do not constitute two future source families. They do NOT establish that FBSDE is generally inferior, or that a general NDU System 2 cannot improve with a calibrated critic and suitable evidence.

## Test, replication, and fail-closed semantics

The original four artifacts were actually downloaded locally from GitHub and byte-verified. **10/10 tests ran against those four REAL original ZIPs**, normal Python and separately with `python -O`, zero failures/skips. The two remote source/test blob hashes match the original locally tested Git blob hashes:

- `archived_e14_independent.py`: `71aef6ad405707364079f58792144835ac49741f`
- `test_archived_e14_independent.py`: `39dcaa63e4ffcbb8f26c4ad820a2a6ca7e2ad583`

The local independently recomputed aggregate is committed as `ACTUAL_E14_ORIGINAL_FOUR_ARCHIVES_20261015.json`; its file SHA256 is `f221a37f5f0fa0fdfb07fc8801553601482a2ced662b7cf74ca4c0ddfefabf6f`. Only sanitized aggregate results are retained. No original ZIPs, credential, pretrained weights or human row labels are committed.

The scoped read-only GitHub Actions workflow re-fetches exactly the four original artifact IDs and outer SHA256s, runs real-original tests normal and optimized, recomputes the aggregate and byte-compares the checked-in result in both original head and prospective merge profiles. An expired, queued, missing, failed or mismatched ZIP **fails**; it does not become a zero outcome or a synthetic fallback. The new exact source CI must complete before it is called hosted-qualified.

```sh
HEPTA_E14_BLIND_SOURCE=/original/11947743374.zip \
HEPTA_E14_BLIND_MERGE=/original/11947373682.zip \
HEPTA_E14_SCORE_SOURCE=/original/11946818427.zip \
HEPTA_E14_SCORE_MERGE=/original/11947358809.zip \
PYTHONPATH=qualification/shared-stem-system2-architecture \
  python3 -m unittest discover -s qualification/shared-stem-system2-architecture \
  -p test_archived_e14_independent.py -v
```

The six-arm prospective System 2 causal experiment remains separately blocked on complete real candidate/verifier/critic execution, identical source data, equal total compute, original human question-level score, and measured full lifetime cost. **No NDU production selection, physical Cell Split, main merge, external effect or FinalUse.**
