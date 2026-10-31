# The frozen joint audio likelihood has an incorrect observation support

The registered source allocator chooses one recording for each digit within a
matched writer/speaker group. Consequently, all equal-digit pairs reuse the
same WAV on their left and right: 4 of 40 independent-qualification pairs and
11 of 170 confirmation pairs. The exact metadata census and byte identities
are recorded in `EVIDENCE_ALIAS_AUDIT.json`.

The same deterministic preprocessing and frozen evaluation-mode CNN return
the same label for two identical inputs. For these pairs, the observed pair
therefore lies on the diagonal. The frozen model instead uses
`pair_likelihood = kron(digit_likelihood, digit_likelihood)`. In the column for
target `(t,t)`, it assigns off-diagonal probability
`1 - sum_o digit_likelihood[o,t]**2`, which is positive for every digit in the
actual frozen table. The JSON records all ten numerical values.

This is a demonstrated support mismatch. Independent digit errors are not a
valid observation model for this part of the registered task construction.
This audit does not establish how much the mismatch contributed to any
calibration or policy result. It changes no candidate, threshold, cohort,
protocol or outcome. A repair needs an observation model that accounts for
duplicate evidence or a fitted joint observation law, a new registration and
independent qualification. The present model's joint-likelihood correctness
remains unresolved.
