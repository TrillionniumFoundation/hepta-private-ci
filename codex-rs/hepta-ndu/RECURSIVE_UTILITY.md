# Deterministic recursive utility implementation boundary

This additive sub-slice of `NDU-1-DETERMINISTIC-UTILITY-BASELINE` implements the
finite-horizon scalar backward recursion in `docs/learning/NDU_FBSDE_SPEC.md`.
It does not close the entire NDU-1 package or advance the D0 capability claim.

`evaluate_recursive_utility` consumes one immutable `RecursiveUtilityPath`.
Events carry ordered identities, exact preference-state digests, already
normalized instant utility and discount. The terminal value must have a nonzero
independent-outcome reference. The objective, episode, coefficients and units
are byte-bound. The host must authenticate these references: a nonzero digest
alone does not establish a trusted observer, legal action or true outcome.

For n in 1..512, the algorithm sets U[n] to the supplied terminal value and
computes U[k] = clip(instant[k] + discount[k] * U[k+1], lower, upper) in reverse
order. Multiplication reuses the crate's signed Q32 nearest/ties-to-even
primitive. Addition and projection use i128 so an intermediate sum exceeding
i64 is safely projected rather than wrapped. Invalid input domains, discounts,
sequence, duplicate events or missing outcome references reject the entire
path; missing reward is never substituted with zero.

Discount one is permitted for this finite-horizon computation only. No
infinite-horizon contraction, stochastic FBSDE solver, conditional-expectation
regression, learned coefficient, preference identifiability or policy efficacy
is claimed. Vector utility/Pareto analysis remains the existing separate API.
The receipt includes all U values, projection count and a digest over context,
inputs and outputs, with `AuthorityPosture::DENY_ALL`.

The NDU-GV-001 regression requires exact raw values
`[5755256177, 4509715661, 4294967296]`. Other tests cover signed values, zero/unit
discount, projection, maximal intermediates, immutable replay, input binding,
malformed inputs, missing outcomes and bounded horizon. Complexity is O(n)
time and memory with a hard n limit. No store, pointer, selected artifact or
production caller is constructed. Persistence, independent outcomes and
composition with the selected preference trajectory remain integration work.

Qualification runs locked all-target compilation, `just test --locked -p
codex-hepta-ndu`, strict Clippy and formatting at exact source and actual-base
synthetic merge. Existing APIs and dependencies are untouched. Rollback removes
the additive module/exports; acceptance and activation require separate review.
