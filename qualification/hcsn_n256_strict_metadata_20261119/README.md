# Strict metadata profile for the original N256 gate

The original first-step contract accepts malformed decoded JSON because Python
equates `False` with `0`, `True` with `1`, and integral floats with integers. Its
null-placeholder checks also compare values without requiring the named keys.
The synthetic controls retain these observed old behaviors instead of rewriting
the historical source or its evidence.

`contract.py` is a separate successor profile. It pins and executes the exact
original contract bytes, recursively checks exact built-in JSON types and complete
key sets, and delegates the numerical gate values to that original contract.
The source request must equal the pinned original HOLD request, including its
bindings. The valid receipt's canonical JSON bytes are unchanged. This is an API
for already-decoded JSON objects; it does not authenticate records, perform
numerical work, admit execution, or parse raw JSON with duplicate keys.

The original source files remain byte-for-byte unchanged. The old comparison of
69,728 coordinates contains 1,291 bit mismatches and remains **RED**. The strict
profile still requires zero mismatches; it does not replace that requirement with
an absolute tolerance. Existing callers of the old namespace are unchanged;
future metadata consumers must explicitly select this successor profile.

## Actual controls

Source was frozen in local commit `878688d4165` before the two controls ran.
`SOURCE_FREEZE.json` SHA-256 is
`0cc5e5551dba8ace26d1201a8c894e0dd5e44cb446b137d7f23b1f80473c937a`.
The Linux cost harness includes each complete child process, imports included.

| Mode | Controls | Old malformed records accepted | New malformed records accepted | Child wall / CPU seconds | Peak RSS KiB |
| --- | ---: | ---: | ---: | ---: | ---: |
| Python | 38 | 28 | 0 | 0.047375 / 0.046634 | 10,496 |
| Python `-O` | 38 | 28 | 0 | 0.626186 / 0.625751 | 14,232 |

Each mode also accepts two valid controls and rejects the original numerical
failure/scope-inflation controls. Optimization does not disable the checks.
The only attempt is retained under `evidence/attempt001`, including both raw
stdout/stderr streams and complete child cost records. There are zero model
calls, matrix exponentials, optimizer updates, and authentic receipts generated.
The longer optimized process includes startup/bytecode work; no speedup claim is
made. `just fmt` runs after the controls as required by `AGENTS.md`.

The predeclared command is `python -m
qualification.hcsn_n256_strict_metadata_20261119.run_controls`; it refuses to
overwrite `attempt001`. `REMAINING_GATES.json` records the separate scientific,
historical, external-custody, and sealed-evaluation gates identified by this
read-only audit. None is silently relabeled by this metadata repair.
