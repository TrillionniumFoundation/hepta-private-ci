# E14 — original-human MultiRC: Reader adequacy before costly NDU/FBSDE routing

**2026-10-15 — Research / Draft / DENY_ALL; no production mutation.**

Parent: E13 #2162, original source HEAD `7aff0bed9f0c69f55c74cef833122a35ad20cdd7`. This is a separate stacked child (not an amendment to source ownership in the unrelated MultiRC #2064 or #2167 branches). No selected Stem, Neuron, Reader, NDU owner, Q24/Q32 wire, signed FinalUse, Artifact CAS, Evidence WAL, release, or `blocking-ci` is changed.

## Actual original evidence, not synthetic labels

The exact **original** successful public-pretrained ModernBERT + trained four Readers is GitHub Actions run [`38663684650`](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/38663684650), immutable artifact `11946621518`, ZIP SHA-256 `1a9b485b6b1ee28c952934069b2cd4d765a17742655f3f3cb3339d3ca672ad17`. The selected source is the original `aps/super_glue` MultiRC at revision `4e14482c58d790d467ecfb29b6790e1917bf8756` with validation Parquet SHA-256 `5eb64893afc5af7828b2f3b41d6a4574eb7a82cbb17c86c75842f5f95f679ada` (306,376 bytes).

The original trained ModernBERT reader archive contains **4 evidence passages, 8 questions, 33 existing human-annotated candidate answers**. No new pretrained model execution is claimed in E14: this is a retrospective evaluation of complete original physical logits, not a new MultiRC model or authentic future window.

| Original frozen Reader | Human-label correct | Brier (two-class) | Near-invariant within-question candidate probabilities |
|---|---:|---:|---:|
| Conditioned | 16/33 | 0.6198974 | 8/8 |
| Mean pooling + query | 17/33 | 0.4968649 | 0/8 at predeclared 0.001 |
| No-evidence | 16/33 | 0.5081490 | 0/8 |
| No-query | 19/33 | 0.6912319 | 8/8 |

These are archival original owner results, **not** a new independent benchmark or a measured causal gain. Only 4 passages and eight question groups; candidate rows are highly correlated. In particular, high apparent no-query accuracy is not evidence of true reasoning because the output is candidate-insensitive and its Brier is worse.

## Scientific question and fixed label-blind comparison

On the EXACT 33 public-pretrained human-candidate logits, hold the same historical Reader features and question support; compare **original four fixed arms** against three additional retrospective routing policies:

- `fixed_confidence`: choose mean pooling when original conditioned posterior is within 1/8 of 0.5.
- `cheap_one_map`: map the original conditioned posterior through ONE E12 registered nonlinear finite stochastic tree, and choose mean pooling if the absolute root value is at most 9/100.
- `e12_full_tree`: run full bounded E12 nonlinear Picard/FBSDE computation, with independent global-prefix correctness checked; choose mean pooling only when the *entire certified root interval* lies within 9/100.

The **9/100 cutoff is exploratory**: it was chosen using label-blind model-output geometry to separate cheap and full decisions, rather than preregistered before all model outputs. It must not be represented as a future-time confirmatory threshold. It is never tuned against human-label outcomes; future independent source families must freeze the rule beforehand.

**Actual label-blind original archive execution (one assistant local CPU):** 33 genuine MultiRC candidates executed E12 at depth 3. `fixed_confidence` switches 15; cheap one-map switches 15; full E12 with conservative root error interval switches 9. The cheap and full policies differ on **6/33** decisions. This is *not* task accuracy: only an independently sealed scorer with original human annotations can evaluate if any of six changes helped.

### Strong label isolation

The original GitHub ZIP embeds some already-scored metadata. The prediction process validates the complete pinned ZIP digest but decompresses **only** the immutable pre-score audit (`multirc-native-candidate-audit/audit.json`) and its original pre-score seal. It NEVER decompresses the historical `scores.json`, the original raw validation Parquet, or any original labels. Mutation tests verify even an altered embedded post-label scores member is never read through the blind API. The CLI never lets a caller bypass the registered ZIP digest.

A separate **GitHub Actions job** downloads the original human-label validation Parquet **after** a create-only proposal SHA is uploaded by the blind job. The scorer rechecks all original paragraph, question and candidate identities against source Parquet; 33 exact IDs must be recovered. It independently replays the E12 whole-tree nonlinear map and its exact contraction, quantized iterations, `Z Sigma=B` and full prefix/martingale state. The original independent 4-arm human-label result must also be reproduced from the raw labeled source within numerical tolerance, else no E14 score exists.

All hypothesis and model costs are differentiated: original prepaid actual 4 shared-Encoder forwards / 33 question encodings / 132 four-arm Reader calls, any hypothetical second Reader switching, local E12 Python mathematical CPU, score/verification cost. No conversion of these disjoint observations to fake end-to-end online latency or energy.

## Fail-closed acceptance

- If the original source is absent, incomplete, hash-different, label-inconsistent, unregistered, or archived score cannot be independently reproduced, the experiment is **unavailable**, not zero success.
- Do NOT assert NDU is useful merely because one route obtains a better retrospective count. The registered E12 utility is an *unidentified mathematical toy*, not fitted to semantic correctness; a positive transfer must be verified on new source/time groups and complete matched costs vs cheap Critic/Bellman before promotion.
- Reader's source- and answer-conditioned capacity is a separate prerequisite. Current 8/8 near-insensitivity of original conditioned Reader is a direct bottleneck, not something FBSDE iteration can repair by itself.
- Preserve unrelated genuine-human semantic training and Head re-forward PRs #2119, #2125, #2137, #2140, #2152, #2167. Do not mix their unqualified future results into this independent historical archive.
- `production_accepted=false`; `blocking-ci` not waived; no source promotion or `main` merge; Draft and `DENY_ALL` throughout.

## Exact commands

~~~sh
ROOT=qualification/shared-stem-system2-architecture
export PYTHONPATH="$ROOT"
export HEPTA_E14_ARCHIVE=/tmp/11946621518-original.zip
python -W error::ResourceWarning -m unittest discover -s "$ROOT" -p 'test_e14_*.py' -v
python -O -W error::ResourceWarning -m unittest discover -s "$ROOT" -p 'test_e14_*.py' -v
python "$ROOT/e14_multirc_route.py" --prelabel-archive "$HEPTA_E14_ARCHIVE" --output /tmp/e14-prescore.json
PRED_SHA=$(sha256sum /tmp/e14-prescore.json | cut -d' ' -f1)
# Only in separate human-label scoring process after sealed prediction exists:
python "$ROOT/e14_multirc_score.py" --archive "$HEPTA_E14_ARCHIVE" \
  --prelabel /tmp/e14-prescore.json --prelabel-sha256 "$PRED_SHA" \
  --validation-parquet /tmp/original-locked-validation.parquet --output /tmp/e14-scored.json
~~~

**No new continuous-time stochastic FBSDE theorem, no natural language generation/Decoder, no 4096 Cell production qualification, no three actual future observation windows, no causal System 2 gain, no signed FinalUse.**
