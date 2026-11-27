# E12 global action-gap on archived original pretrained MultiRC (shadow only)

## Frozen lineage

Research-only child of PR #2563 at frozen HEAD `82a56ab8aecc3a255761ce578a22773b278c9011`. Preserve all original E12 #2143, local Cell #2508, learned continuation #2520/#2521 and action-gap #2563 source and tests. This experiment adds a **separate real-model archival observation bridge**, not a replacement for the E12 math owner, pretrained Reader, NDU/Neuron runtime or artifact selector. The PR is `DRAFT / SHADOW_ONLY / DENY_ALL`, with no FinalUse, main merge, online tool invocation or real Cell Split.

## Exact public source and isolation

- Real original ModernBERT / four trained Readers: original public MultiRC artifact ID `11946621518`, ZIP SHA-256 `1a9b485b6b1ee28c952934069b2cd4d765a17742655f3f3cb3339d3ca672ad17`.
- Prelabel original 33-candidate model evidence: `multirc-native-candidate-audit/audit.json`, SHA-256 `c0a7ae08d682349ce8b8ebd3bce14fcfe5203f9c636cea3944a85a10f45f4840`. The source-only proposer decompresses **only this and its original `COMMITTED.json`**; it never opens the scored ZIP members or validation labels even though they are historically present in the complete ZIP. Byte hash, semantic observation digest, four Reader weight IDs, 4 passages / 8 questions / 33 real answer candidates, exact provenance and existing 132 Reader calls must be verified.
- Original human validator: `aps/super_glue` dataset commit `4e14482c58d790d467ecfb29b6790e1917bf8756`, file `multirc/validation-00000-of-00001.parquet`, SHA-256 `5eb64893afc5af7828b2f3b41d6a4574eb7a82cbb17c86c75842f5f95f679ada`. **Only** postseal independent scoring process downloads and decompresses it.
- Original human owner score digest: `3a3fd807585dd09ef4f089391dc68db4b008e87b69060f68f384a07daaa9f8e4`. Human score must independently reproduce conditioned **16/33**, mean-pool **17/33**, plus two remaining original Reader metrics; no label-fabricated fallback is permitted.

## Preregistered policy and exact mathematical control

For each existing original candidate, obtain its *previously executed* conditioned logits and compute stable class-1 probability `p`. Set `x0=round_ties_even((2p-1)*1024)/1024`, depth 3. Use the complete finite stochastic, nonlinear E12 law, `a=0` or `a=1/3`, `sigma=1/3`, `horizon=3/4`. Run PR #2563's **zero-initialized**, exact-rational, per-action whole-tree global contraction/error-gap decision for at most 32 map calls. The fixed actions map as follows:

| E12 action | Original Reader / response |
|---|---|
| `direct` | frozen conditioned Reader |
| `coupled` | frozen mean-pool-query-fused Reader |
| `stop` | abstain, never silently count as correct |
| `HOLD_UNRESOLVED` | abstain |

The E12 utility penalty `1/512` for the coupled action is a **synthetic law constant** and not a measured paid Reader call. The mapped action is a declared heuristic, **not** a learned or calibrated continuation utility for MultiRC. Therefore the FBSDE certificate can establish *which action optimizes this discrete synthetic law*, not human question-answer correctness. This is a critical negative-control boundary; do not re-label mathematical `Y` as original task utility. No pretrained Reader or Stem weights are loaded or trained in this follow-up.

Controls presealed alongside the gap policy: original conditioned, mean-pool, no-evidence, no-query, fixed-confidence (conditioned probability within `1/8` of `1/2` switches to mean-pool), and E12 cheap one-map. The frozen second Reader's archived logits are only a **counterfactual offline replay**; no new conditional online invocation is claimed. STOP/hold coverage is reported separately, with abstentions not assigned a synthetic prediction or Brier. Full lifecycle includes original 132 historical Reader calls for the *whole original experiment*, and **new** proposer CPU/map-count separately; it is invalid to sum meters from unrelated hosts as equal physical serving cost.

## Independent review and acceptance

After original blind SHA seal, distinct scorer Runner verifies every original row, mapping, old model logits, selected policy, original E12 `operator`, independent full-prefix `reference`, exact terminal/martingale `audit`, every interim Q16 residual and bound, complete legal-action scheduler and all Cell map calls. Only then may it obtain authentic pinned MultiRC publisher labels and recompute baseline Owner human metrics and all policy outcomes. Persist exact source/merge Git identity, raw sealed decisions and source hash; upload independent **aggregate** result, not raw human Parquet.

No source-independence is established by 33 answers from 4 passages. Treat passage as the independent cluster, do not run naive candidate-level statistical significance. A full future-date/source-disjoint task set, a meaningful learned terminal utility, independent outcome observer, online matched physical Encoder+Reader+FBSDE+Verifier+training costs, decoding correctness and negative-transfer controls are required before an NDU System 2 efficacy claim.

This bridge **must remain NO-GO** regardless of human accuracy, until new independent prospective evidence and `blocking-ci` / Architecture / authority gates succeed. No automatic promotion, Cell Split, code execution or external effects.

## Reproducible code paths

- `e12_gap_multirc.py`: original Model archive label-blind read, 33 pinned whole-tree proposals, strict deny-all receipt.
- `e12_gap_multirc_score.py`: original global-math replay, human publisher identifier recomputation and owner-score reconciliation.
- `test_e12_gap_multirc.py`: source-only security, real archived score, synthetic math-shim adversarial tests (shim is explicitly **not** original E12 proof).
- `.github/workflows/hepta-e12-original-multirc-action-gap.yml`: exact HEAD & synthetic merge, two distinct original-archive/label-isolated GitHub jobs. Original E12 native math imported by actual reviewer; do not replace with test shim.

Developer-only local source validation (requires the exact original GitHub artifact):

```bash
export PYTHONPATH=qualification/shared-stem-system2-architecture
export HEPTA_E12_MULTIRC_ORIGINAL=/path/to/original-11946621518.zip
python -m unittest discover -s "$PYTHONPATH" -p 'test_e12_gap_multirc.py' -v
python -O -m unittest discover -s "$PYTHONPATH" -p 'test_e12_gap_multirc.py' -v
```

Local tests are not a passing hosted source-HEAD/synthetic-merge or real original human-score receipt. Fail closed if either hosted original artifact, independent E12 math, human publisher Parquet or original Owner truth is unavailable.
