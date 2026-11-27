# Semantic probability transport after the support-filter preservation failure

Previous support conditioning failed both seeds because it slightly reweighted
unspecified attributes. Do not relax that gate. This new opt-in serving operator
edits ONLY explicitly set attributes of each proposed decoded semantic outcome,
then sums its probability mass into that edited outcome's existing learned
decoder slot. No mass is discarded or normalized by retained support. Original
wrong keep attributes are preserved as wrong; no source-label oracle repairs them.

Both observed text and image semantic maps must be complete bijections of the
12 finite RGB classes. Missing/duplicate semantics cause terminal refusal. No
nearest target, best model, renderer, pixel overwrite or uniform fill is allowed.
Destinations may have zero prior probability: this is transport to an existing
learned output, not the old zero-mass conditioning operation. Mode/schema/profile
identity is distinct and explicit; old support-condition/default profiles reject.
All-keep is exact no-op. The original independent text/image law factorization
remains; the learned decoder and all parameters remain unchanged.

For every command, the joint distribution of ALL unspecified attributes is
structurally unchanged in each marginal. Specified-word compliance, correct
semantic mass and cross-modal agreement are therefore largely mathematical
properties of this edit, NOT independent evidence of learned generation ability.
Actual pixel MSE from learned decoder destinations and quality-sensitive reward
still need measurement. No natural-image or NDU training benefit is claimed.

## One fixed continuation experiment

Use exactly the same two supervised synthetic RGB bases, seeds11/23, and same
516 validation rows per model as the prior support study. No retraining, model
choice, test split or original digit payload. Include baseline, previous support
conditioning and new transport side-by-side on every row. Main metric gate is
unchanged: on partial commands with1/2 set words, both seeds independently require
joint-success and external-reward gain >1e-10, pixel MSE <=baseline+1e-10, and
both modalities' unspecified preservation >=baseline-1e-10. Report every0/1/2/3
set-word subset and full inventory. No pooling to rescue a failed seed.

Additional correctness checks: every request's whole free-axis joint distribution
is conserved to absolute1e-12; all-keep is bit-exact; output obeys explicit words;
strict profile roundtrip/binding and observed-semantic bijection. Nine new literal
tests cover the complete36-command lattice, permuted decoder maps, zero-prior
destinations, old wrong keep attributes, tamper/mode rejection and no-op identity.
The old support helper is reused unchanged, not silently repaired.

One child includes tests/imports/two restores/two decoder observations/1032
forward rows/1032 old-condition calls/1032 transport calls/all metrics/exit.
New synthetic-only shared EX lock, CPU0/one thread,10CPU/30wall/256MiB/4MiB bounds,
fullwait4, no retry/extension/successor within this attempt. Same frozen source
allowlist and exact two model payloads; no network/descendants. Preparation,
review, supervisor tail and previous base preparation remain nonzero/unknown
outside this child; reusing models is not free or equal-total-budget evidence.
Original digit experiment and prior support gate remain failed/unavailable.
