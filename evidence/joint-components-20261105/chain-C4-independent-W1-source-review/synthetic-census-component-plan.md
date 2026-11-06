# C4: existing synthetic Dense/Sparse census components

## Decision and source boundary

The existing `pon_work_expensive_v1` example can execute the two synthetic
children of the original campaign directly. This requires no model material,
new algorithm, source change, Mode-A round or learning experiment. Keep the
original owner parameters: **64 attempts, 8 samples, reuse over 16 actual
attempts, target indices 0 and 1, and 300 seconds per native child**.

This is a static plan, not an execution receipt. It qualifies neither the full
17-child campaign nor the five routing tiles, model adoption, public task
admission, public service liveness or globally cheapest legal work. The frozen
source is C4 commit `8df4b21d893906570d48f5beafabb3b31e0aefbc`, tree
`6f5aaa2af0432e27e24b6bd2ad18013ab4423d14`. No Cargo, native census, model
generator or NumPy baseline was executed for this review.

The machine-readable `synthetic-census-component-plan.json` records complete
argument vectors, expected identities and source blobs. The native example
is blob `c258df9b422991ed29b56d03d7f43c7b6d125a9d`; the original owner is
`dba09f0efa05ef56595dc764c9a89c8595b58063`; the unchanged reader is
`ead1eed53c01c5d8d78112515f95a79e89669f58`.

## Build and two exact native invocations

The documented release build is in
`evidence/pon-work-expensive-v1-20261105/README.md`, lines 451–470, blob
`a0275e9c439a02638ebabfaf54cd59193b5f15cd`. It specifies Rust 1.95.0, default
release settings and two build jobs, with no RUSTFLAGS/profile overrides.
The exact C4 toolchain file independently pins 1.95.0. The package default
features are empty; this plan does not enable optional OpenSSL or all features.
The original build command is:

```sh
cargo build --offline --locked --release \
  --manifest-path trillionnium/Cargo.toml \
  -p trnm-crypto-primitives --jobs 2 \
  --example pon_work_expensive_v1 --example pon_shared_material_v1
```

The documented preceding checks are `bash scripts/project-preflight.sh` and,
if locked dependencies need acquisition, `cargo fetch --locked --manifest-path
trillionnium/Cargo.toml`. The build produces two examples; only the census
example is executed here. Its original owner and reproduction section provide
no build timeout. Do not label another runner's 900-second build allowance or
five-second termination grace as this owner's original budget. Build/setup
receipts remain separate from the two native deadlines.

With `C4_CENSUS_ELF` set to the actual retained executable from that exact
locked build, the two native argument vectors are:

```sh
"$C4_CENSUS_ELF" --work-expensive-v1 \
  --attempts 64 --samples 8 --reuse 16 --target-index 0 \
  --seed d74433233739073f8237d5efa7d7fe9f2bf7b686a4634c425c2dabc6bed68944

"$C4_CENSUS_ELF" --work-expensive-v1 \
  --attempts 64 --samples 8 --reuse 16 --target-index 1 \
  --seed d74433233739073f8237d5efa7d7fe9f2bf7b686a4634c425c2dabc6bed68944
```

Each has empty standard input and **no `--material` argument**. The source
owner creates these synthetic commands at lines 414–423. The exact historical
two commands and this seed are recorded in
`reproduction.json.exact_current_native_replay`, blob
`3d7786976af8eb2b18a2ab20e56bc10b27ff28ec`. Selecting that already recorded
seed predeclares a reproducible mathematical input, with no new freeze/reveal
or model construction. The historical execution used another source anchor;
its binaries, timings and qualification are not inherited by C4.

The native program's own defaults are **32/3/32**, so omitting the explicit
owner counts would silently shrink/change this experiment. The executable
does not accept a timeout argument. Its launch must keep the original
`exchange -> run_bounded` boundary: `timeout=300`, stdout cap 256 MiB, stderr
cap 1 MiB, empty bytes on stdin, repository-root cwd. The deadline starts
before process spawn and covers exchange/wait; the existing group cleanup is
retained. Two sequential native deadline allowances sum to **600 seconds**,
excluding build, source guards, reader work and cleanup overhead. That sum is
not a new whole-task deadline or a claim the processes already ran.

## Exact coverage and pairing

Each child requests **9 classes × 8 samples × 15 arms = 1,080 cells**;
the two children request 2,160. The classes are periodic-dense-fixture,
full-rank-field, zero, identity, rank-one, sparse-diagonal,
continuity-maintenance-v1, left-zero-right-rank-one and
right-zero-left-rank-one. The last two use the original census recipe
`(row + 1) * (column + 3)`; do not substitute the other suite's recipe.

Arms include all existing fourteen producers and the fifteenth
`lazy-full-limb-sparse`. Arm zero constructs `Task::new(..., FullLimb)`;
arm fourteen constructs `Task::with_preparation(..., FullLimb, Sparse)`.
Both use the same `TargetHit` materialization mode. Every supported cell
retains all 64 attempts, even after a winner, and performs four actual
construction/destruction epochs of sixteen attempts. Unsupported specialized
constructors retain their one paid setup and zero attempts; they are not
treated as zero-cost successes. Thus 1,080 is a requested-cell count, not a
requirement that every specialized arm be supported on every class.

Dense and Sparse must each complete 72 cells per target, 4,608 attempts and
288 setups. Across all arms/targets, 138,240 attempts and 8,640 setups are
upper bounds if all requested cells were supported, not observed counts.
Every hit executes the native and scalar verification entry points. Raw
attempt/phase records must be retained, including failures and misses.

Challenge generation binds task, seed, sample and attempt index and omits
arm, target and reuse generation. Accordingly, each class/sample/index has
the same trace and ticket across Dense/Sparse and both targets. Target zero
is `7f` followed by 31 `ff` bytes; target one is `07` followed by 31 `ff`
bytes. Work identity includes the target; target cohorts are not additive
chain work.

The original execution order rotates fifteen arms over only eight samples.
It is not balanced over all positions: sample zero places Dense first and
Sparse last; samples one through seven place Sparse immediately before
Dense. Preserve the original eight samples and report the remaining
order/cache confounding. Same mathematical input does not imply an unbiased
or fully randomized timing comparison.

## Apply the original reader, then bind the requested component

For each preserved child stream, run the unchanged reader with its original
split and budgets:

```sh
python3 -B scripts/pon_work_expensive_reader_v1.py \
  <receipt>/synthetic-target-0/native.jsonl \
  --out <receipt>/synthetic-target-0/reader.json \
  --calibration-samples 2 --budgets-ns 1000000 5000000 20000000
```

Use the corresponding target-one paths for the second stream. This is the
same reader invoked by the owner; its CLI does not need the model or Mode-A
inputs. It checks exact row order, nine class names, canonical material,
task hashes, challenges/tickets, cross-arm equality, all misses, both
accepted verifier verdicts on every hit, setup/reuse/teardown accounting,
phase sums and complete final counts. It does not authenticate execution or
clock honesty by itself.

The independent outer binding must also require:

- Process exit zero; no timeout, output overflow or process failure; raw and
  stderr retained with hashes; exact C4 source/build/actual ELF binding.
- Native schema `pon-work-expensive-native-v2` and exactly the fifteen source
  arm names. Reader exit zero alone is insufficient because it deliberately
  supports old v1/fourteen-arm data.
- The declared seed and target, 64 attempts, 8 samples, reuse 16 and exactly
  nine expected materials. The reader can validate a smaller internally
  consistent stream; it cannot infer the intended request.
- `requested_cells=1080` and complete plus unsupported plus failed counts
  summing to 1,080, with failed count zero. Dense/Sparse must satisfy the
  complete-cell counts above; unsupported optimization cases remain visible.
- Matching task/A/B identities and class/sample trace sequence digests
  between target-zero and target-one reports. Each stream's original reader
  already checks the cross-arm equality within that target.

Keep original two-sample calibration and six-sample evaluation. The original
reader selects by aggregate calibration producer CPU with a fixed tie order,
then evaluates later samples; do not use per-sample fastest-arm selection.
The 1/5/20 ms prefixes count only actually completed and destroyed cache
epochs. They are postprocessing, not executed early-stop trials.

Producer timing includes actual setup, all attempts, per-attempt proof
cleanup and final epoch teardown. Material acquisition and identity/rank
preparation are separate. Verification/evidence/output and continuous
observed-cell/native/process clocks have distinct scopes; nested clocks must
not be summed. Full-rank material generation inside the common synthetic
recipe cannot be charged as an unavoidable attack cost for zero input.

## Why the full material owner is excluded

The full owner additionally requires a v1 manifest, model.json, tasks.json
and five 32,768-byte `tile-i/material.bin` files. It reconstructs and binds
all five routing tiles, runs five Mode-A shared-material children, and adds
ten supplied-material census children to these two synthetic children.
That is seventeen native children at 300 seconds each, with a separate
twenty-minute Mode-A round window and additional Python/build work.

The exact C4 tree contains the default historical integer-model input,
consumer rows and evaluation bundle; it contains no already expanded
eight-file material directory. `material-input-readback.json` records their
exact blobs, canonical/hash/partition checks and limited retrospective
scope. No generator was run. Generating those routing inputs, its 100-repeat
baseline and Mode-A execution are unnecessary for the requested synthetic
Dense/Sparse comparison and are outside this component plan.

This finite supplement can identify cheaper observed legal preparation and
specialized strategies on its nine classes. It cannot establish a global
attacker lower bound, contemporary task registration permission, service
liveness or complete-model adoption. Original legal-v3 and reused-v3 remain
separate experiments with their original recipes, horizons and challenge
domains.
