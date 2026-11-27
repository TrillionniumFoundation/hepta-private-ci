# Explicit command support: helps set words, fails preservation gate

The legacy finite RGB generator already receives instruction features. This
experiment adds an **opt-in serving distribution**, not a new training loss:
condition the generated content law on explicit color/shape/position words,
using the semantics observed from its actual learned pixel decoder and text.
All-keep is an exact no-op. Set words restrict support; keep axes are not filtered.

**Both frozen gates failed.** Support conditioning changed the relative weights
of unspecified attributes and slightly reduced their preservation in both seeds.
Do not accept the intervention merely because commanded attributes improved.

## Actual controlled result

Two previously frozen supervised RGB bases were read without updating them.
Each evaluated all 516 validation requests from 86 groups. Primary results use
only the 312 requests with one or two explicit set words, avoiding full commands
that already specify the entire target. Full, all-keep and each word-count subset
are retained in `SUMMARY.json`, not selected by outcome.

| Partial commands | Seed 11 | Seed 23 |
|---|---:|---:|
| Joint-success change | +0.055754 | +0.054458 |
| Fixed external reward change | +0.056807 | +0.055214 |
| Actual pixel MSE change | -0.003159 | -0.003042 |
| Unspecified text preservation change | -0.000909 | -0.000231 |
| Unspecified image preservation change | -0.000995 | -0.000416 |

The last two failures are not rounded away: the preregistered tolerance was
1e-10, and both modalities had to be noninferior in both seeds. All-keep output
laws were unchanged; no empty-support or zero-mass request was excluded.

Joint-success increase is itself largely structural: if the correct outcome
survives support restriction, renormalization increases its mass. It is **not
independent evidence of improved learned generation capability**. Pixel quality,
external reward with contradiction penalties and unspecified-attribute retention
provide the nontrivial checks. Text/image marginals remain an independent product;
joint consistency is measured rather than guaranteed.

## Reusable implementation

`control.py` defines the explicit, model-bound profile, command parser, decoded
support projection and strict opt-in serialization. Unknown/mixed profiles,
malformed requests, empty support and zero mass reject without epsilon/fallback.
No target label, renderer, learned-weight update or decoder substitution enters
the projection. `test_control.py` has nine literal tests, including a permuted
decoder mapping that distinguishes observed semantics from latent IDs.
Run them with `python -B -m unittest -v test_control`.

`PLAN.md` preserves the frozen design; `VALIDATION.json` states verification scope.
This package does not contain private original digit data or model checkpoints.
The original digit chain was unavailable and was not recreated or accepted.

## Cost and next mechanism

One completely waited child, including tests, imports, two restores, decoder
observation, 1,032 forward rows, projection, metrics and exit, used **0.429883 CPU
seconds**, 0.447970 wall seconds and 36,240 KiB peak RSS. Bounds were 10 CPU seconds,
30 wall seconds and 256 MiB; CPU0/one thread under a new synthetic-only shared lock.
Reused base preparation had recorded prefixes 0.219982/0.227947 CPU seconds;
upstream imports/exports/supervision are not thereby free. Supervisor final tail
and preparation/review costs are unknown, not zero. Extra serving work is not an
equal-total-budget result, and no training or natural-image benefit is claimed.

The diagnosed issue motivates a DIFFERENT next candidate: transport probability
mass by changing only explicitly set semantic attributes, preserving the remaining
attributes of each proposed outcome. It requires a learned decoded-content map
with all needed destinations; absence must reject. This is a future experiment,
not an already validated result and not a relaxed threshold for this failed gate.
