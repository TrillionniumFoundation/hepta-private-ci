# Native NDU integration and reproduction

This experiment invokes the existing Rust owner functions
`codex_hepta_ndu::evaluate_recursive_utility` and
`codex_hepta_ndu::evaluate_candidates_with_policy`. It does not replace either
algorithm with a Python utility implementation. The Python signed integer
recurrence independently checks every native recursive value and evidence hash.

## Registered contract

The registered recursive profile is
`hepta.ndu.recursive-utility.scalar.q32.v1`: finite-horizon scalar additive
utility, signed Q32, nearest rounding with ties to even. Its owner recurrence is
`U[k] = clip(instant[k] + discount[k] * U[k+1], lower, upper)`. This adapter rejects
projection and uses zero terminal value. Forecasts and realized task paths use
discount one; tests additionally exercise nontrivial discounting and signed ties.
The bounds are ±1,000,000 task-return units. No entropic or multiplicative
utility profile is inferred or substituted.

The candidate evaluation is the existing V2 contract. Native `abstain` is
mandatory. Task action `STOP` is explicitly mapped to this exact zero-cost,
zero-effect candidate; `WAIT` and `REPAIR` retain their own candidate identities.
All output keeps the native `DENY_ALL` authority posture and
`safety_certificate=false`. A supplied contract-check digest records provenance;
it does not certify that a stochastic forecast is a realized fact.

The experiment's instantaneous reward is 0.6 times actual active duration, minus
0.5 per actual failure, minus the repair fee once when repair is performed.
The resource axis records repair expense for feasibility inspection; it does
not subtract the fee again. The learned boundary bias adjusts the deployed
choice only and is absent from both forecast utility and actual reward.

For forecast action values, the plan after the current candidate is always
`WAIT_AFTER_CURRENT`. The deployed controller replans at each half-unit decision.
These plan utilities therefore are not the Bellman values of the deployed
replanning policy. The study retains both predicted plan values and independently
scored environment outcomes. The full native realized receipt is constructed
from actual transitions, with state, input, fee, clock, deadline, and STOP
continuity checked before evaluation.

## Source identities

The owner source is pinned to
`ed6f8c6645c927249cec0d3395f6bae21f278739`. The transport is adapted from the
existing HIA bridge at
`4b6391e116949af0c7e59776baead67271856bdb`, with separate schema, organ, policy,
units, and coefficient identities for this experiment.

`NATIVE_SOURCE_MANIFEST.json` lists every required owner source file, original
Cargo manifest, compile-time fixture, and original test runner with its exact
commit, Git blob SHA-1, byte length, and SHA-256. Before compiling, the builder
checks SHA-256 and recomputes the Git object hash as
`SHA1("blob " + decimal_byte_length + NUL + original_bytes)`. The original owner
source, crate manifests, workspace dependencies, and workspace Cargo.lock are
never edited by the builder.

The pinned source closure can be obtained in either of two ways:

1. Use a checkout of the experiment branch that retains the unchanged owner
   files from the pinned base. Pass its repository root as `--source-root`.
2. Materialize each manifest record from that record's exact commit and path
   through authorized GitHub access. Preserve original bytes and directory
   structure. Recompute both hashes before storing the record. The closure is
   sufficient for this scoped adapter build; unrelated workspace members are
   not compiled. Do not replace a missing fixture with a generated placeholder.

`native-Cargo.lock` preserves the donor's exact registry packages, changing only
the independent adapter package name. An isolated build manifest points to the
original owner crate paths and inherits their original dependency features.
With `--download-dependencies`, registry archives are fetched at the exact locked
version, checked against Cargo's SHA-256 package checksum, safely unpacked, and
registered in an offline vendor directory. The subsequent build and test both
run `--locked --offline`.

## Rebuild

Requirements are Python 3.12 with NumPy and SciPy for the experiment, Rust
1.95.0, Cargo, `just`, and `cargo-nextest`. The native builder itself uses only the
Python standard library. Give the builder writable output and target directories;
compilation uses one job, no debug information, and no incremental cache to keep
its intermediate storage modest.

From the repository root, substitute local absolute tool and output paths:

```bash
python experiments/first_passage_cell/build_native.py \
  --source-root "$PWD" \
  --output /path/to/first-passage-native \
  --target-dir /path/to/first-passage-target \
  --toolchain /path/to/rust-1.95.0/bin \
  --nextest-bin /path/to/cargo-nextest-directory \
  --just-bin /path/to/just-directory \
  --download-dependencies
```

The builder compiles the standalone adapter and invokes the repository's actual,
unmodified `just test` recipe and its `scripts/run-nextest.py` runner, scoped to
`hepta-first-passage-ndu-bridge`. It does not invoke `cargo test` directly. A
successful build writes `NATIVE_BUILD.json` and a verified runnable executable
into the output directory only after all six native protocol tests pass.

The original formatting gate is `just fmt`. Python source outside the original
runner's selected formatter scopes is additionally syntax-checked and exercised
by the experiment tests; a successful formatting invocation must not be described
as a comprehensive Python lint result.

To run the native and numerical Python tests against a rebuilt adapter:

```bash
HEPTA_FIRST_PASSAGE_NATIVE=/path/to/first-passage-native/NATIVE_BUILD.json \
  python -m unittest experiments.first_passage_cell.tests.test_ndu -v
```

A manifest's `binary` may be absolute or relative to the manifest directory.
`NativeNduPort` checks the executable SHA-256, the source-manifest SHA-256, the
embedded source commit and adapter digest, the registered profile, and the live
`--identity` result. The study's freeze additionally pins the exact executable
hash. A rebuild at different filesystem paths or with different build tools may
produce a different executable hash even when the native numeric behavior is
unchanged; it needs its own recorded build identity and experiment freeze.

The compact retained gzip executable archive is a copy of the tested binary,
not a new compilation. Extract it to the manifest's named binary path, make it
executable on Unix, and let `NativeNduPort` verify it before use. Do not change a
frozen manifest's hashes merely to accept a different executable.

## Validation receipt

`evidence/NDU_VALIDATION.json` records the actual six native tests, eleven distinct
Python tests, exact source and binary identities, fixed-cohort native versus
independent quadrature agreement, and 10,000 independently sampled renewal paths.
The finite-tree test enumerates every leaf of a depth-three tree and compares
native recursion with an exact rational expectation, allowing only the declared
Q32 rounding budget.

The numerical checks cover the declared diagnostic fixtures. The quadrature
comparison is not a universal error certificate, and its timing is a small
matched-input diagnostic rather than a system-wide speed benchmark. Policy
performance claims must come from the separate frozen, paired confirmation
study's actual subsequent net rewards.
