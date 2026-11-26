# N256 uniformization precision policy

Status: **HOLD / all_closed=false**.

This separately frozen source-only stage defines how a future external N256 uniformization certificate must compose five nonnegative binary64 error components: Poisson tail, sparse-row action rounding, Poisson-recurrence rounding, accumulation rounding, and serialization rounding. Every addition is rounded outward with `math.nextafter`.

The declared provider-only upper bound may not understate the outward sum and may not exceed the unchanged original scaled-error limit `0.01`. This does not allocate that whole limit to the provider, prove that a future candidate plus provider comparison passes, or replace separate per-quantity scientific gates. It only prevents a future certificate from hiding provider error or weakening the original limit.

The policy also requires immutable provider/admission/operator/roster/segment identities and all six scientific certifications required by #6337. No actual certificate is created or admitted here. Tests use one synthetic certificate record; there are zero N256 provider, candidate, oracle, model, optimizer, or training calls.

This does not close actual FP64/tail certification, provider admission or external independence, every roster operator, the 18,225,028-record stream, three-way comparison, saved-state byte pairs, resources, migration, fullnetwork/equal-budget benefit, asynchronous cost, C2 full replay, HPCA external custody, or production adoption. Historical RED/UNKNOWN and #6247 finite-domain failure remain unchanged.

