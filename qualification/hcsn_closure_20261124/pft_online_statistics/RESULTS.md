# Durable fixed-feature statistics: engineering qualification

The four registered synthetic checks passed on their first execution. This stage adds a per-peer durable ledger to the fixed-feature research path from #7071; the historical-cache runner is reviewed in a separate stacked change.

## Why this stage exists

The original one-shot ring binds its run manifest and rejects duplicate origins within that run. An online peer also needs a stable representation contract, atomic persistent admission, declared-sample deduplication, and a compare-and-swap head across concurrent processes and restarts.

The new ledger binds parent, feature program, normalization, target/loss, time semantics, epoch, dimensions, numeric policy and regularizer. It admits raw Gram, RHS and full output-by-output `yTy`, validates the joint statistics matrix, and applies ridge once after summing contributions in canonical batch-ID order. Identical retries are idempotent; conflicting bytes, reused declared sample IDs and incompatible contracts are rejected.

## Executed evidence

| Registered control | First-run result |
| --- | --- |
| Eight processes replay one batch | One accepted, seven idempotent |
| Two different batches race one head | One accepted, one stale-head rejection; refreshed retry succeeds |
| Process exits before commit / after commit | Exit 41 rolls back; exit 42 persists and replay is idempotent |
| Reverse order, reopened store, independent augmented least squares | Identical candidate objects; maximum weight error `1.4155343563970746e-15` |

The rejection check also covers changed bytes under the same batch ID, declared-sample overlap, changed representation identities, count/digest mismatch, stale CAS, invalid statistics and invalid regularizer. All leave the ledger head unchanged. This is four test methods with multiple explicit controls, not four training trials.

The protocol was committed as `2f1550b2e05505a2940687c2a9d7dbb08ef2fd31`; candidate code was committed as `4c0e781e0cb1abb3b2412db0d3c116b75808349b` before execution. Python 3.12.14, NumPy 2.3.5 and SciPy 1.17.0 were used with one BLAS thread. The outer synthetic run took 1.6856 seconds. No candidate or endpoint was selected after seeing results.

`synthetic-evidence.tar.gz` retains the execution-time source bytes, actual child PIDs/exit codes/receipts, candidate export, frozen command, raw test log and formatting receipt. Its SHA-256 is `3039d0a9d1ca019ca9219b0227bb166ed899cb52151b0b4edb5af5d66cef7a9c` (15,705 bytes).

Official `just fmt` exited zero on the partial checkout; qualification Python is outside its automatic dispatch. Locked-version Ruff 0.15.13 then formatted the new files. Their before/after ASTs are equal. Tests were not rerun after formatting, as required by `AGENTS.md`.

## Boundaries

These are independent local OS processes. The crash control terminates a process, not a machine or its storage hardware. Deterministic ordering was checked within one numeric environment; arbitrary BLAS implementations need not produce identical floating-point bytes.

Hashes bind declared bytes and model identity; they do not authenticate a user, source, or honest contribution. Sample deduplication assumes stable declared sample IDs. An attacker can forge new IDs or plausible positive-semidefinite statistics. Authentication, admission economics and adversarial contribution checks remain separate work.

This change does not establish real-user A-to-B adoption, learned-Circuit advantage, faster end-to-end foundation-model training, global hidden-layer credit, or native Chain settlement. Existing scientific gates and old receipts are unchanged.
