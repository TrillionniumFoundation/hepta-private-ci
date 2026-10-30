# Allocate fixed training work away from structurally zero-gradient rows

The serving-aligned study improved both seeds, but NDU's additional greedy-text
nonregression failed one seed. Do NOT tune rho/anchor/lr or weaken that gate.
This separate mechanism is motivated by a proved property: with fixed learned
decoder and semantic transport, a fully specified command has parameter-independent
final loss. Its per-row current gradient is zero. Raw sampling still spends work
on these rows. This is NOT an Adam moment-reset or architecture intervention.

Define eligibility solely from the ten visible request-word features: retain
rows with at least one keep word (including all-keep), exclude fully specified
commands. Do not inspect targets, predictions, loss, validation or model rank to
choose rows. Let pi be eligible fraction in the unchanged training population.
Uniformly sample eligible rows and multiply BOTH anchor and utility gradients by
pi. This keeps the original finite-population mean gradient mathematically
unchanged; the omitted loss terms are constant in the trained parameters.

At a fixed theta, with iid sample size B, covariance(full sampler) minus
covariance(weighted eligible sampler) equals
pi*(1-pi)/B times E[g_active*g_active^T], which is positive semidefinite.
The original objective is a mean of per-request A/N losses, NOT one nonlinear
CE over the data population. The guarantee is about pre-clipping gradients,
before floating roundoff. Clipping, Adam moments and adaptive updates are nonlinear:
their expectations are NOT preserved, and lower variance does not guarantee
generalization, greedy accuracy or scientific success.

## Fixed paired continuation

Same two supervised RGB bases,seeds11/23. full/informative sampling × A/N gives
8 cells, each300 updates,batch64,lr.003,anchor.2,rho1.5,shared encoder and heads,
frozen decoder and final semantic-transport service. No other objective/weight,
parameter, architecture or serving change. Compute all four raw/aligned utility
branches and both anchors in every arm as before, then select the ALIGNED loss.
Both arms multiply by a scalar (1 or pi) before unchanged clipping/Adam.

Full sampler uses exactly seed+9000's prior row draw/full-low coin sequence.
Informative sampler uses fixed seed+9100 for uniform eligible row draws and the
SAME precomputed full/low masks as its paired full sampler. Eligibility, pi and
all batches are frozen before loading any model. Save selection counts/hash.
All four full-sampling final tensor digests MUST exactly match prior aligned
finals; otherwise terminate without changed tolerance or another run.

Every model gets300 updates; all8 frozen before validation generation. Same
train1560rows/260groups and validation516rows/86groups, both full/low channels.
No TEST split and no original digit data. All final models and both bases are
reported; reused validation is exploratory, not independent confirmation.

Primary gate is unchanged in strength: macro full/low partial-command312-row
metrics. BOTH seeds must pass BOTH informative-N minus full-N (allocation gain)
and informative-N minus informative-A (NDU increment). Each needs rho1.5 CE gain
>=.005, no text-mass/greedy-text/joint-success loss beyond1e-10, and pixel MSE
increase <=1e-10. Report informative-A−full-A and full-N−full-A as non-rescue
controls. No seed/model selection, threshold relaxation or post-hoc batching.

Seven new literal tests qualify command-only eligibility, complete36-command
lattice, all-keep retention, empty/malformed refusal, unbiased weighted mean,
exact covariance identity, and nonlinearity of an adaptive update. Prior exact
aligned gradients and semantic transport are reused unchanged. Four exact full-sampling final reproductions plus the eight-model
pre-validation freeze barrier serve as additional runtime controls.

One bounded complete child under the same NEW synthetic-only shared EX lock:
20CPU/90wall/512MiB/4MiB per file,CPU0/one thread,complete wait4, no retries or
extensions. Includes tests/imports/train generation/sampling/two restores,
8clones/2400updates/7220forwardbatches/471120forwardrows/evaluation/output/exit.
Source/review, supervisor tail and historical base-preparation costs remain
additional/not zero. Equal operations/useful updates and a common cap are not
equal actual total spend. No original-study recovery or deployment claim.
