# Lane A foundation: current implementation truth

This directory is the closed-world, source-checked companion for the Lane A
foundation modules. The canonical registries and each module's `TECHNICAL.md`
remain authoritative for ownership, contracts and target architecture. This
package is authoritative for a narrower question: **what the checked-in native
source implements now, and what remains target-only**.

A target design is not an executable capability. A source root is not an
activation receipt. A passing fixture is not operator acceptance. The verifier
in `scripts/verify_lane_a_foundation.py` fails when those states are collapsed
or when a source anchor drifts.

## Closed-world module set

The set is exactly:

1. `platform.types`
2. `platform.wire`
3. `kernel.authority`
4. `kernel.operations`
5. `kernel.evidence`
6. `auth.authbus`
7. `secrets.heptabao`

`MODULE_TRUTH_MATRIX.json` records six orthogonal status axes, current
capabilities, target-only capabilities and source anchors for every module.
Each module-specific document includes the current executable contract, the
target-only design, non-claims and verification obligations.

## Closure claim

This package closes repository-controlled documentation gaps for Lane A:

- current source and target design are separated;
- misleading production/durability claims are prohibited;
- the V1 wire layout is normative and source-checked;
- authority and Bao source-adjacent specifications are linked into one lane
  truth surface;
- the evidence migration range is explicit;
- drift is checked at exact source head and synthetic merge candidate.

It deliberately does **not** claim production activation, operator acceptance,
release, distributed anti-rollback, a durable operations backend, a durable
AuthBus policy/quota service, or any external effect not proven by an exact
candidate receipt.
