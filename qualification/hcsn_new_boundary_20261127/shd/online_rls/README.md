# Charged online hidden targets, soft recursive fitting and a fixed protected subspace

This is a reduced audio-classification adaptation of specific 2026 editing principles. [Li et al., M-ORE, ICML 2026](https://proceedings.mlr.press/v306/li26ji.html) estimate module-specific locality and use a fixed subspace and online recursion for pretrained multimodal models. [Wang et al., RLSEdit, IJCAI 2026](https://doi.org/10.24963/ijcai.2026/265) write key–values under soft parameter/anchor regularization. The input here is labeled speech. We did not borrow an original LLM's hidden target optimizer, claim a factual-edit replication or treat its hidden values as known.

Each of the three original FSDD/Arabic parents receives the same 480 Google Speech Commands utterances from 435 training speakers in four approximately equal, speaker-group-preserving stages. The sole editable tensor is the real 32-by-16 synaptic matrix multiplying two-phase financial boundary messages. For each new example a full present-state HCSN trajectory gives logits. Plus/minus perturbations on each of six time points yield 12 further trajectories, simultaneously resolving all independent receivers and their subsequent recurrent effects. A 10-by-10 damped solve maps the true label residual into a six-by-16 target drive displacement. Its 6,240 new forward trajectories per candidate path are charged. Each method receives the same one-visit new cohort and 960 predetermined old example exposures (480 per domain): RLS aggregates those old keys into its initial weighted anchor precision; same-site BP/LoRA compute the old output error on those identities as they arrive. Shared parent features and old predictions are charged in the full wall-clock search. The 3-parent study includes at least 8 real roles: exact KEEP, soft RLS, fixed old-low-variance subspace RLS, no old key anchor, wrong-label RLS, normalized plain forward-feedback on the same real target, exact same-site Adam and rank-four LoRA.

For each six-row new key K and currently supplied value V, the update uses F=G K-transpose and a triangular solve on I+K F, then W += F(I+K F)^(-1)(V-KW) with the corresponding Woodbury G update. The initial precision includes both a weight-drift ridge and an old-key anchor. The eight- or sixteen-dimensional fixed edit subspaces use smallest-eigenvalue old key directions, which have measurable nonzero old-key energy. They do not certify zero drift for every old input. The terminal online matrix agreed with batch least squares over the exact realized path targets (including priors) to 1.29e-14 or closer. That establishes the numerical solution of the local surrogate only. Initial pilot-409-full was fully charged separately in the evidence and kept after matching the identities of the prior's old examples to the BP stream; all scored candidates used the corrected common identities.

The batch parents/dataset had previously published cold results. This separately registered experiment froze 24 never-before-scored online matrices and all four-stage histories in 43c35f45c31ee11853ee7e618adf36d39c5bd747 before computing their actual held-out performance. All compared source components are in the sibling cross_source package. Full direct SciPy A7 + first-passage replay on the official cold population accounted for 1,056,000 class scores. Maximum absolute difference 0.000089; no changed predictions. The gradient-control supplement independently checked 12,288 real coordinates over 24 inputs. Max difference from FP64 PyTorch AD was 1.09e-7. Its sample directional finite differences were 3.35e-5 at worst. The original exploratory low-precision finite-difference diagnostic in result.json uses an epsilon close to interpolation rounding and has higher errors. Prefer the independent high-precision values in gradient_check.json.

| 3-parent mean change versus unchanged parent | GSC (240 held-out people) | FSDD (2) | Arabic (22) | All-path search time |
|---|---:|---:|---:|---:|
| Full soft RLS | +0.05 pp | +0.10 pp | +0.06 pp | 11.93 s |
| Fixed subspace RLS | −0.11 pp | 0.00 pp | −0.02 pp | 23.14 s |
| No old-key anchor | +0.08 pp | +0.30 pp | +0.05 pp | see receipts |
| Shuffled latent targets | +0.03 pp | −0.07 pp | +0.06 pp | 12.11 s |
| Normalized forward feedback | +1.11 pp | +1.37 pp | −0.67 pp | 11.86 s |
| Same-site Adam | +1.28 pp | +3.77 pp | −0.82 pp | 10.27 s |
| Rank-four LoRA | +0.60 pp | −0.67 pp | −0.77 pp | 11.85 s |

New source KEEP was 17.59% speaker-balanced. Full RLS effect CI [-0.11,+0.23] pp; the fixed subspace [-0.23,-0.02] pp. Neither passes the +2pp new/old-retention requirement for any seed. Same-site Adam passes one seed. Stage-one training-speaker accuracy was unchanged by the final stage for all selected full/subspace RLS runs. This coexists with tiny task acquisition. At 30 prespecified systematic training rows per parent, installing the unrestricted per-record latent target directly raised the true predicted class probability by a mean of 6.13–10.24 points. A shared soft-RLS matrix gave root-mean-square score changes of only 0.021–0.054, and restricted RLS 0.003–0.014, compared with 0.406–0.622 for the plain forward-feedback comparator. These are calibration diagnostics, not untouched test probabilities. Early-cohort, measured norm, probe, source, per-person and per-seed results are available. Full precision held-out task scores, exact edits and normalization are retained, including negative results. The fixed-subspace search explores twice as many ranks as full RLS. Search times compare the observed candidate grids; they do not measure abstract single-write complexity.

Restore the sibling cross_source and its UJI direct-law helper first (see its README). In this directory run:

```bash
python restore.py .
export HEPTA_MULTILINGUAL_INPUT="$PWD/../cross_source/data" OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1
python replay.py score
python replay.py diagnose
python replay.py gradient
```

Only the independent gradient check needs PyTorch. Per-arm cold classification and full analytical replay need NumPy/SciPy. From an isolated copy, `python replay.py fit --seed 409 --arm full` recomputes a full online-path grid; elapsed fields naturally depend on machine. SEAL.json refers to the original measured fit receipts. The source benchmarks, participant allocation and raw PCM hashes are the same verified assets in the sibling cross_source folder.
