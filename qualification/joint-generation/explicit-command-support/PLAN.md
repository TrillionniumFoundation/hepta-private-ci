# Explicit request-word support conditioning — frozen new RGB control study

The available old RGB generator already sees ten instruction features through
its encoder. This candidate does NOT claim the condition was absent. Failed
gradient-projection/momentum hypotheses are not rerun. Instead this new opt-in
serving profile conditions the existing categorical output law on requested
explicit words, using fixed observations of actually decoded text and pixels.
There is no new training gradient, reward, renderer output or model update.

Only set-color/set-shape/set-position words constrain support. The legacy keep
word adds no filtering on its axis. Thus source-attribute preservation is NOT
guaranteed by the filter and must be evaluated. All-keep is exact baseline law.
Each text/image marginal is independently renormalized; the original product-law
factorization remains, and joint consistency is measured, not guaranteed.
Ratios are preserved only among surviving positive-probability outcomes.
Empty decoded support or zero retained mass rejects; no epsilon or fallback.
The profile identity binds the model digest, vocabulary order, decoded semantic
mapping and explicit mode. Loading must opt in and rejects mixed identities.

## Fixed experiment

Read both newly frozen old-RGB supervised base inference bundles, seeds11/23,
saved BEFORE any peer adaptation. Do not select a peer's trained winner. Reuse
does not make upstream pretraining free: report its recorded cost separately.
The original digit FIT/models/lock remain unavailable; these are NOT replacements.

Generate only the old RGB validation split, six fixed noise variants per group:
86 source-scene/instruction groups,516 rows. No test split request or evaluation.
For each model prepare its learned decoder observation once, infer baseline
policies once, parse only x's last ten explicit instruction features, then apply
the opt-in conditioner to every request. Ground truth/source group IDs enter only
metric evaluation after conditioned policies have been produced. All516 rows,
including empty/zero-mass outcomes, are accounted for; a refusal fails the study
rather than selecting surviving rows. Model digest and original bundle SHA must
remain unchanged. No parameters, optimizer states or new model checkpoints saved.

Report baseline and conditioned actual decoded joint success, greedy success,
consistency, pixel MSE, fixed external expected reward, conditional CE at rho1,
retained mass, outcome entropy and support size. Report both modalities' probability
of preserving each unspecified source attribute. Evaluate every group of0/1/2/3
explicit set words separately as well as the full inventory. All-keep preservation
is not counted as a guaranteed property; it is simply baseline compatibility.

Primary gate uses ONLY partial commands (one or two set words), avoiding the
tautology of full target specification. BOTH seeds must independently have:
- mean actual decoded joint-success increase >1e-10;
- fixed external expected-reward increase >1e-10;
- mean actual pixel MSE no higher than baseline+1e-10;
- unspecified-attribute text preservation and image preservation each no lower
  than baseline-1e-10.
Full commands or one favorable seed cannot rescue a failed gate. These are
exploratory finite-task gates, not significance tests or a natural-image result.

## Bounded once-only execution

Nine handmade fixture tests run first in the same child. Model/dataset code is
exact copied legacy source; only two explicit synthetic base bundles are readable.
No unrelated filesystem payload, network or descendant process in worker. The
NEW synthetic-only shared lock is not the missing original digit benchmark lock.
CPU0, six thread variables1, observed one thread; child limits10CPU/30wall/256MiB,
4MiB per output file. Parent completely wait4-reaps child and records CPU/RSS/wall,
including tests/imports/generation/restores/decoding/projection/evaluation/exit.
No repeated run, model selection, test access, budget extension or silent repair.
No same-total-budget, training-improvement, deployment or original-study claim.
