# Native compiler follow-up and recovered source identity

This checkpoint preserves the exact files retrieved from the third native
attempt, followed by a separate cloud source candidate. It does not replace
the earlier 399 and 82 failures or claim that any complete learning chain ran.

## Third native attempt

The actual `ai395` source was
`b9d00ed288e6056f47c3617b2eec36cabe25e2ec`, tree
`cf6955ee9a05c9709d2c02b7467f445e4abbc089`. It was clean before and after
execution. The same-source helper build completed in 99.40 seconds. The
three-library `just test` invocation requested Agentd, Agent Protocol and
Learning Ledger, with zero retries and `--no-tests fail`.

Test compilation failed with eight E0659 diagnostics in
`cell_q24_task_outcome_control_tests.rs`: its `super::*` import left
`assert_eq!` ambiguous between the imported `pretty_assertions` macro and the
prelude. The ordinary stage ran from 07:35:15 to 07:37:02 UTC on 2026-11-12,
exited 101, and produced no fresh JUnit. **Zero tests executed. The requested
UID0 parent suite did not start.** The earlier ten Ledger fixture diagnostics
were absent from this attempt; that does not establish a passed library suite.

`b9-retrieved-originals.tar.gz` contains exactly three original UTF-8 files:
the final driver record, ordinary `run.json`, and the complete ordinary
`command.log`. The latter is 49,334 bytes with SHA256
`a48a42d8a24c4d2d46c60f4416d1d7221619f3abf7358bea69de1ba1eb04c186`.
Each original was checked against the byte count and SHA256 supplied by the
actual file read; the compressed archive was extracted and checked again.
`b9-originals-inventory.json` records every member and the archive digest.
This is a partial attempt checkpoint: the complete helper Cargo JSONL and
other host files were not retrieved and are not silently reconstructed.

The durable full caller scan on b9 was actually started as job
`1a1ceafdd3e-2564-17b8`. Its final result remains **unknown**. Later read-only
observations did not return; ending the local observation wait did not cancel
the remote job. The separate second macro-fix operation on that host also
has no observed result. Neither unknown operation is counted as PASS, FAIL,
or as the source candidate below.

## New cloud source candidate

The recovered common repository imported the retained original Git bundles.
Two explicit, small source commits then repaired fixture imports:

| Local commit | Remote commit | Exact tree |
| --- | --- | --- |
| `c043cfada0b935d325f149c352874659d6d91182` | `bfa82689b26150929a5ffdb55ee4b153d545550e` | `cf6955ee9a05c9709d2c02b7467f445e4abbc089` |
| `2420fb01d7d26d7c851f48dd24ad2f9385272259` | `d8b03c34ecdf324e5f0ff5345789e510571763c1` | `24c507b1536b4dd7d92a87525f1adf13fa455b54` |

The first entire tree equals the observed b9 tree; it has a different commit
identity. Its only change from 82 imports `pretty_assertions::assert_eq` in
the Ledger frame fixture. The second imports that macro explicitly in the
Outcome control fixture. No assertion, deadline, role check, closed caller
set or verifier was changed. Both source commits passed actual `just fmt`
and `git diff --check` before commit.

The new second tree passed the existing RunStart read-only source closure
suite (10 tests) and original Outcome control source closure suite (16 tests)
by running their ordinary `unittest.main()` entry points. The exact commands,
raw output, timestamps and unchanged clean before/after source snapshots are
in `macrofix-2420fb01-source-qa/`. These are lexical source checks. This
checkpoint records no native execution of the new second tree.

`prefix-publication-mapping.json` preserves all 49 original integration
stages plus these two fixes. Each remote Git tree was checked against its
local tree before creating the remote commit. The branch was advanced using
an expected old SHA and without force. This mapping records source custody;
successful publication is not a qualification result.

The complete ordinary positive, NoUpdate, and daemon-plus-Root cold-restart
acceptance counts remain **0 / 0 / 0**.
