# PQ recovery CI selection audit

This is a local source and synthetic-log audit. **Native tests executed: 0.
Hosted CI triggered: false.** The passing fixtures below do not qualify the Rust
implementation, a production recovery root, provider effects, or capacity.

## Exact inputs

`ci-baseline-workflow.yml` retains upstream workflow Git blob
`c07b903bc589096f5927ee224abd10684d9a3c82` byte for byte. This imports one workflow,
not a materialized or executed complete upstream checkout. The new validator
extends the method of historical validator blob
`f54bb28e39e648b15fbb6051d4139ba5e55006c2`; that historical evidence is unchanged.

The audited working tree had HEAD
`f04033d852ee9c1c9ba88a9fc48c21b798c39f97`. The workflow itself was modified after
that checkpoint. `ci-selection-audit.json` binds the exact edited workflow,
validator and inspected Rust files by their hashes. No Rust source changed during
this CI-only continuation, and its result does not retroactively extend any
native run on the earlier checkpoint.

## Mandatory selection

| Group | Selected tests | Command deadline | Change |
| --- | ---: | ---: | --- |
| Dispatcher | 14 | 3,600 s | Preserved |
| AuthBus process controls | 3 | 1,800 s | Preserved |
| Evidence snapshot / ACK provenance | 7 | 600 s | Preserved |
| PQ recovery frontier | 9 | 600 s | Replaces the two historical signed-frontier controls |
| Agentd evidence recovery processes | 4 | 1,800 s | Added from `kernel_evidence_product` |

The nine frontier tests and four process tests use individual exact-name `-E`
selectors. The old V1-only test name is replaced with
`recovery_frontier_refuses_valid_classical_v1_and_v2_signatures`. All five groups
feed the same mandatory audit, which requires each selected test to pass exactly
once, verifies the raw log hash and original command exit code, and refuses
missing, skipped, duplicate or unexpected test observations.

The original 24 selected controls, runner matrix, source/merge lanes, environment,
job and existing command budgets, action pins, formatter and artifact retention
are preserved. The dependency-fetch step now says "locked current dependency
graph". The original two linter packages remain, with
`codex-hepta-infer-worker-host` added to compile its changed tests and binary under
the existing scoped `just fix` gate. Pull-request path triggers include that
crate and this CI evidence family.

## What was actually checked

`ci-validate-selection.py` parses the actual workflow and executes its actual
inline mandatory-audit code against disposable synthetic receipts. It checks
the preserved workflow structure, exact filters and minimum counts, and all
37 named Rust test definitions and their test attributes. It also asks the
repository's existing nextest wrapper to recognize the exact filters.

All **154 source-audit fixtures** matched their expected outcome:

- One complete 37-test fixture was accepted.
- Removing, ignoring or duplicating each of the 37 tests was rejected: 111 cases.
- Each of five groups rejected an absent group, zero observations, a wrong log
  digest, a nonzero command exit, failed status, wrong passed count, a failed
  summary, or an extra test: 40 cases.
- The preserved 24 controls alone and the obsolete classical-V1 test name were
  rejected: two cases.

No synthetic receipt is saved as a native execution receipt. The result kind is
`CI_SOURCE_AND_SELECTION_AUDIT_FIXTURES_ONLY`, with `HOLD_NO_GO` qualification.

## Reproduce

From this repository with Python 3 and PyYAML available:

```bash
python3 evidence/pq-recovery-owner-20261105/ci-validate-selection.py \
  --repository "$PWD" \
  --output /tmp/hepta-pq-recovery-ci-source-new.json
```

The output file must not exist. Reproduction runs only the source checks and
synthetic audit fixtures. The actual 37 native controls and the linter remain
mandatory future CI execution; this local source audit supplies no execution
credit for them.
