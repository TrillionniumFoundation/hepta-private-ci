# ADR 0001: policy-admitted safety semantics

- Status: accepted for source candidate
- Date: 2026-09-26

## Context

Earlier recall evaluated maximum OOD and contradiction groups over the entire generated union. A low-score, disabled-channel or otherwise non-admitted candidate could therefore force whole-request abstention. Contradiction-support rows also lacked proposition polarity, so multiple same-side records could be mistaken for a conflict. Zero activation and zero-weight edges had ambiguous semantic treatment.

## Decision

1. Build a deterministic policy-admitted set before OOD and contradiction decisions.
2. Count channel coverage only from positive-weight admitted evidence.
3. Represent contradiction identity as proposition digest plus `Affirms` or `Denies` polarity.
4. Treat same-polarity multiplicity as corroboration, not conflict.
5. Require strictly positive active-node activation and strictly positive `minimum_activation`.
6. Treat zero-weight edges as semantically inert.
7. Compute active confidence using activation weighting.
8. Preserve fail-closed structural validation and version digest domains when semantics change.

## Consequences

The recall result is resistant to low-value poison candidates and false same-side contradiction abstention. Policy authors must calibrate admission thresholds because rejected candidates no longer participate in global safety checks. If a deployment needs a broader safety scan, it must define a separate explicitly weighted safety-admission policy rather than relying on non-admitted data.

## Required tests

- all candidate permutations produce one result and receipt;
- adding a low-score candidate cannot erase a higher-score result without admitted safety evidence;
- zero activation produces no support;
- zero-weight edges do not alter recall or contradiction receipts;
- same-side contradiction support does not abstain;
- opposite-polarity support for one proposition abstains when configured;
- receipt candidate counts always equal emitted candidates.
