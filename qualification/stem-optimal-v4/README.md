# Original hard-charge V4: independent cheap lexical controls

**DRAFT · SHADOW_ONLY · HOLD_NO_GO · DENY_ALL · NO MAIN MERGE · NO MODEL PROMOTION · NO CELL SPLIT.**

Frozen parent is V3 commit `bc8e83331294d43daf122224941e967bd29af15d` / PR #2590. V4 adds four new qualification files and one read-only original-publisher workflow; it does **not** edit V1/V2/V3 evidence, original pre-trained model producer, main, inference Worker, FinalUse or NDU.

## Reason

The true original V1 32-case BANKING77 cohort had 32/32 learned-Head and 32/32 **cheap supervised centroids** for Granite47 and Granite97. That establishes no incremental correctness from the gated Head. V3 preregisters a distinct four-way fee/charge cohort but its original model CI still requires exact physical evidence. V4 preregisters two much cheaper controls on **the same V3 cohort** before inspecting any V3 heldout result:

- **Word 1–2-gram, train-only TF-IDF, normalized class centroid**, fixed softmax temperature 8.
- **Character 3–5-gram, train-only TF-IDF, normalized class centroid**, same fixed temperature 8.

Only the original 64 selected TRAIN texts and TRAIN labels build vocabulary, IDF and supervised class centers. The 32 original TEST texts contribute no vocabulary, IDF, class or hyperparameter fit; the producer cannot access their labels. Every algorithm is deterministic, is pure Python standard library, and reports measured process CPU/wall/maxRSS. It performs **zero** pretrained Encoder forwards, uses no neural Head, and reports energy/p99 as null, not fabricated physical values. Lexical vocabulary bound is 100,000.

## Custody, independence and limitations

1. A publisher-source owner reacquires the original `PolyAI-LDN/task-specific-datasets@57ec275d8078af65b7731c2a98be812d844a6d6b` CSV byte files, checks exact SHA-256 and runs the frozen V3 hard-charge cohort preparer. Source envelope contains 64 TRAIN texts and labels plus 32 label-free TEST texts.
2. On a separate job, the cheap producer computes all two-arm prelabel 32-case probability vectors and uploads SHA-checked raw prediction receipt without gold. It does not import or call any pretrained Transformer.
3. On a separate later runner, a new independent reviewer reopens the original publisher labels, reselects the source/TEST roster **without importing the lexical producer**, replays every train-only feature/IDF/centroid numeric prediction, verifies every per-case probability within 1e-12, and recomputes 4-class accuracy/Brier. The only allowed disposition is `HOLD_NO_GO`.
4. Tests include synthetic original-layout fixtures only, nonfinite outputs, cohort/label swap, probability tampering, fake resource/model-forward claims and altered source identity. **Tests cannot stand in for original public execution.**

These baselines are descriptive cheap controls. The V4 experiment alone cannot choose an optimal Stem: no matched same-host V3 model execution, no deployed 421M/no-change total lifecycle, prospective source/time cohorts, negative transfer, NDU benefit, independent issuer signatures, p95/p99 or target-host 4,096 Cell studies. Even original matching V3+V4 on a single publisher would be one research canary, not causal promotion evidence.

## Reproduce source-only conformance

```sh
python -m unittest discover -s qualification/stem-optimal-v4 -p 'test_cheap_lexical_v4.py' -v
python -O -m unittest discover -s qualification/stem-optimal-v4 -p 'test_cheap_lexical_v4.py' -v
python -m py_compile qualification/stem-optimal-v4/*.py
```
