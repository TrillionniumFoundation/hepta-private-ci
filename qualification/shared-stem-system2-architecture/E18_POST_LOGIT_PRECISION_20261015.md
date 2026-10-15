# E18 — genuine pretrained Reader output-precision information boundary (research only)

**2026-10-15. DRAFT / DENY_ALL.** Stacked additively on the original E17 #2210 source HEAD. No runtime neuron, training owner, selected model, Q24/Q32 native ABI, artifact store, CAS, FinalUse, MemoryCell, `blocking-ci`, release authority, or `main` is changed.

## Why this is the necessary next control

E17 independently established that the original frozen pretrained ModernBERT `conditioned` Reader is nearly answer-invariant on the eight genuine human-annotated MultiRC questions, while the `no_query` Reader is **exactly** answer-invariant. Existing E15/E16 3- and 5-parameter Heads are still awaiting **actual original-human heldout labels** through their separate queued Actions. An entirely local, synthetic-label Head training success is not real heldout task efficacy.

The missing question for compact Cell inference: if a serving pipeline rounds **both archived original FP32 output logits BEFORE their difference**, does even the tiny remaining conditioned candidate distinction survive? A model architecture ranking cannot be inferred from a single FP32 output study and a low-precision post-processing profile cannot be claimed equivalent to re-running BF16/FP16 model weights.

## Immutable source and independently executed experiment

- Genuine original `multirc-native-candidate-audit/audit.json` from hosted Actions run 38663684650 / ZIP artifact 11946621518, exact outer SHA-256 `1a9b485b6b1ee28c952934069b2cd4d765a17742655f3f3cb3339d3ca672ad17`.
- **4 real source passages / 8 questions / 33 original candidate answers**, **55 within-question answer pairs**. Each source group is a passage; treating 33 rows as 33 independent tasks is invalid.
- The label-blind process calls the existing exact-identity E14 `read_prelabel`. That function decompresses ONLY the original model-prediction and source-seal members, never the scored human-label member.
- Four **post-output** profiles, separately applied to EACH of the two saved original FP32 class logits **before subtraction**: original_fp32; signed `Q24` nearest-even; IEEE binary16 nearest-even; BF16 nearest-even. All input floating-point values must be exact representable original FP32, finite and within the fixed [-8,8] logit domain.
- Independent second implementation uses `frexp`/`ldexp` plus ties-even quantization, rather than the producer's `struct` FP16/BF16 bit manipulation. It recomputes all 33×4×2×4 output projections, 8×4×4 question/pair statistics, the source group identities and every result field. Both implementations agree exactly on the actual archived source.
- Only after the output has been written create-only and byte-sealed does the separate reviewer open the exact archived original-human score summary with SHA-256 `3a3fd807585dd09ef4f089391dc68db4b008e87b69060f68f384a07daaa9f8e4` to confirm **all eight original questions contain both true and false candidate answers**. This is historical original-label provenance, *not* a new human signer or new outcome.

## Actual ORIGINAL pretrained prediction result: candidate-invariant questions

| frozen Reader arm | FP32 original | Q24 on 2 logits | FP16 on 2 logits | BF16 on 2 logits |
| --- | ---: | ---: | ---: | ---: |
| conditioned | 4 / 8 | 4 / 8 | **6 / 8** | **8 / 8** |
| mean-pool + query | 0 / 8 | 0 / 8 | 0 / 8 | 0 / 8 |
| no-evidence | 0 / 8 | 0 / 8 | 0 / 8 | 0 / 8 |
| no-query | **8 / 8** | **8 / 8** | **8 / 8** | **8 / 8** |

The conditioned equal-margin candidate-pair count increases from **36/55** (original or Q24), to **48/55** (post-output FP16), to **55/55** (post-output BF16). All eight registered questions contain originally human-labelled true and false candidates; therefore, in this exact source and **this declared post-output BF16 transformation**, a deterministic answer predictor consuming **only conditioned Reader margin from the fixed same-question output** cannot solve all of any of those mixed-label questions. This is a narrow algebraic representation obstruction, not a claim about token-level hidden features, an adapted full network, richer input, or even a BF16 model-forward execution.

**Important:** Q24 here is a *research post-logit projection* and is **not** a claim that the existing `hepta-neuron` signed-Q24 runtime was invoked. No BF16 or FP16 **backbone model** was re-forwarded. Quantizing the final logits before subtraction is **different** from doing the subtraction in FP32 and quantizing that difference, and different from loading BF16 model weights. Any real deployment comparison must preserve and audit the exact rounding boundary and conduct real physical model forwards.

## Resource and validity boundary

This is offline deterministic arithmetic on the original frozen observed outputs; **zero new pretrained model forwards, zero new trained Heads, zero FBSDE solves, zero observed future human task labels, zero measured serving energy/latency/p99 or complete 4096-Cell runtime**. These 8 questions are from one past source family and carry no power to select a universal optimal Stem or to promote NDU System 2.

Fail-closed tests cover exact archived source, question/pair census, original Q24/FP16/BF16 independent parity, nearest-even positive/negative ties, rejected non-FP32/unknown profiles, altered source digests, forged model/permission flags, invented paid forwards, tampered individual spans, duplicate/missing question rows, tampered ZIP, source-seal timing, and create-only output durability. Tests fail if the genuine original artifact is absent; **no synthetic substitute or skip counts as a pass**.

### Reproduce on original pinned archive

```sh
ROOT=qualification/shared-stem-system2-architecture
export PYTHONPATH="$ROOT"
export HEPTA_E18_ORIGINAL_ARCHIVE=/path/to/exact-original-11946621518.zip
python -m unittest discover -s "$ROOT" -p 'test_e18_*.py' -v
python -O -m unittest discover -s "$ROOT" -p 'test_e18_*.py' -v
python "$ROOT/e18_precision_boundary.py" --archive "$HEPTA_E18_ORIGINAL_ARCHIVE" --output /tmp/e18-blind.json
sha256sum /tmp/e18-blind.json
python "$ROOT/e18_independent_precision_review.py" --archive "$HEPTA_E18_ORIGINAL_ARCHIVE" --blind /tmp/e18-blind.json --blind-sha256 "$(sha256sum /tmp/e18-blind.json | cut -d' ' -f1)" --output /tmp/e18-review.json
```

### Next admissible gates

1. Wait for original-human E15/E16 **actual 4-source LOPO** results before claiming tiny Head learning benefit; report full-question success and cluster-level uncertainty, not 33 independent trials.
2. Run separately measured FP32/FP16/BF16 **real model forwards** with identical complete source inputs, same native tokenization/Head/training and target host on new source/time groups. Compare applying rounding before vs after margin, keep unrounded FP32 as baseline; charge any added projection work.
3. Explore real answer-conditioned Reader training (#2080) and independent cold pretrained re-forward (#2167) if learned Head outcomes do not demonstrate task gain.
4. Retain no-system2/cheap Bellman/Critic baseline, E12-E14 FBSDE negative results and separate production activation/cost/lifecycle safeguards.

`production_accepted=false`, `model_selected=false`, `prospective_learning_improvement=false`, `continuous_FBSDE_certified=false`, `authority=DENY_ALL`. **No auto-merge or deployment; blocking CI and independent architecture gates remain binding.**
