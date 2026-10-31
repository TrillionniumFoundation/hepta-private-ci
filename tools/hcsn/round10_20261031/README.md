# HCSN R10: five executed evidence tracks, 2026-10-31

**Read [the full Chinese report](REPORT_ZH.md) first.** The work supports scoped
process fidelity and actual preread control. It does **not** establish a complete
task-optimal He--Xiong network or superiority over ordinary gates, SNNs or
Transformers. Machine-readable decisions are in [ACCEPTANCE.json](ACCEPTANCE.json).

This continues exact R9 commit `e7eaa5e0be835269636216c8fe8b1ae2f1a22361`, tree
`2182eb6fd29f615a9110e4b84103f1d7e254c41d`, without rewriting its historical evidence.
Publication branch: `research/hcsn-causal-five-track-20261031`.

## Evidence map

| Package | Actually executed | Interpretation |
| --- | --- | --- |
| [dynamics](dynamics/README.md) | Two original-source regressions, 120,000 main Brownian paths, four joint resolutions and one explicit follow-up | Prescribed moving boundaries; residual numerical error remains |
| [value](value/REPORT.md) | Exact finite Bayes--Bellman task, 280 conditional action-value checks, 3 gate families × 3 fit seeds | Same-information analytic advantage not established; repeated confirmation is not new independent data |
| [native](native/README.md) | Fresh Hepta build, 16 tests, 576 process runs over 48 paired worlds, 8 restart pairs, 24 cloned action requests | Exported Q-table decides before content access; latent CTMC firing does not trigger READ |
| [AV main](av/REPORT.md) | 5 recurrent models × 3 seeds × 2 budgets, all small recurrent/readout weights updated | 2/8 primary gates passed, both missing-modality contrasts versus CfC; offline fixed frontends |
| [AV memory](av/memory_followup/REPORT.md) | 15 long-delay training jobs and 15 frozen-checkpoint replays | 0/4 exploratory analytic contrasts passed; useful long-delay retention not established |

The three executed dynamics contracts remain distinct: Brownian renewal,
task-controlled finite CTMC, and freshly parameterized per-step erfc recurrence.
Neither energy nor GPU performance was measured. Figures are descriptive
renderings of frozen data, with their input hashes in [figures/INPUTS.json](figures/INPUTS.json).

## Verify and restore saved evidence

From the repository root:

```sh
python3 tools/hcsn/round10_20261031/verify_delivery.py
python3 tools/hcsn/round10_20261031/restore_evidence.py
```

This verifies four archive identities and all **455 members** before/while
restoring. It refuses to overwrite different evidence. Archive entries and
destination prefixes are bound in [BUNDLES.json](BUNDLES.json). The memory bundle
already contains `memory_followup/`, so its destination is `av/`. Verification in
a fresh root was executed twice. [PACKAGING_PATH_AUDIT.json](PACKAGING_PATH_AUDIT.json)
also documents the one-byte EOF difference of the saved official CfC reference.

The separate [CLEAN_BUILD.zip](native/evidence/CLEAN_BUILD.zip) is the byte-exact
GitHub artifact from the qualified native run: 2,889 members including all work
checkpoints, journals, input payloads, native executables, lockfile and compiler
identity. Its SHA256 is
`4fbd0a8f34061594a26b3707c88fd332fcf7aab3066fa44e4b14fb74c064c681`.
[CI_ARTIFACT.json](integration/CI_ARTIFACT.json) binds source commit, selected
members and the original artifact ID. It is not silently treated as a new build.

## Native build and qualification

The recorded scientific run is at source
`41a38cd4f05924c57d0ff841ea392de10704d9b3`,
[CI 41185622819](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/41185622819).
It passed 11 baseline and 5 preread tests, then ran the process qualification.
The failed first attempt and later successes remain in
[CI_ATTEMPTS.json](integration/CI_ATTEMPTS.json). A conditional no-op step in an
early run is not counted as completed qualification.

`integration/prepare_native.py` restores 60 exact source blobs for three original
Hepta crates at `732e934ba496d90fbe042b8d41d479ef901643e5`. It verifies identities,
retains original Cargo manifests, and generates only an enclosing workspace.
The reference toolchain is Rust 1.95.0 and just 1.43.0. Registry download access is
required on a clean machine. No preserved rlibs are accepted as a fresh build.

For a new attempt, use an empty build/output directory:

```sh
python3 tools/hcsn/round10_20261031/integration/prepare_native.py --build /tmp/hcsn-r10-build
cp tools/hcsn/round10_20261031/integration/qualified_build/Cargo.lock /tmp/hcsn-r10-build/Cargo.lock
just --justfile /tmp/hcsn-r10-build/justfile test
just --justfile /tmp/hcsn-r10-build/justfile build
python3 tools/hcsn/round10_20261031/native/qualify.py \
  --binary /tmp/hcsn-r10-build/target/release/hcsn-owner-preread \
  --output /tmp/hcsn-r10-native-new
```

The six new Rust files were subsequently formatted using the **unchanged repo
`just fmt` recipe** in an isolated checkout with only those six files in scope.
Both `just fmt` and `just fmt --check` passed. Official formatter output was
applied mechanically; the original experimental source and results stay pinned
above. The original/after hashes, exact patch, tool provenance and application
record are in [integration/formatting](integration/formatting/FORMAT_REPORT.json).
This is not a full-tree formatting or full-Codex-workspace test claim.

## Python reproduction without replacing frozen records

Reference runtime: Python 3.12, NumPy 2.3.5, SciPy 1.17.0, mpmath 1.3.0. Plotting
additionally uses Matplotlib 3.10.8. Install [requirements.txt](requirements.txt)
in an isolated environment. Set BLAS thread counts to one for comparable CPU
accounting:

```sh
export OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1
```

Several AV/audit scripts intentionally write beside their source. **Use a new
copy for reproduction**, and do not run those writers inside the frozen evidence
directory. For example, copy this R10 directory to `/tmp/hcsn-r10-new` before
restoring the saved archives, so `av/results/` is absent. If already expanded,
copy source/configuration into another empty directory, excluding old results.

In that new copy:

```sh
python3 dynamics/regression_audit.py --output /tmp/hcsn-r10-regression-new.json
python3 dynamics/moving_audit.py --samples 40000 --output /tmp/hcsn-r10-moving-new
python3 dynamics/distribution_diagnostics.py /tmp/hcsn-r10-moving-new
python3 dynamics/refinement_followup.py /tmp/hcsn-r10-moving-new
python3 value/run.py --output /tmp/hcsn-r10-value-new
python3 value/audit.py
```

Restore the original fixed AV features rather than generating new media:

```sh
python3 av/fetch_transport.py --output /tmp/hcsn-r10-av-parts
python3 av/restore.py /tmp/hcsn-r10-av-parts /tmp/hcsn-r10-av-data
python3 av/check_gradients.py
python3 av/study.py launch --data /tmp/hcsn-r10-av-data --jobs 3
python3 av/summarize.py
python3 av/memory_followup/run.py launch --data /tmp/hcsn-r10-av-data
python3 av/memory_followup/summarize.py --data /tmp/hcsn-r10-av-data
python3 av/memory_followup/inspect_target_sensitivity.py
```

The downloader fixes commit `dca9febc8143c682077fe27d40dbeaa1137bcaa4`, directory
`experiments/hcsn_blocker_closure_v1/av/transport_41156412198/`; it verifies 126
textual parts before the restorer produces 15 files, 22,292,173 decoded bytes.
No raw media is duplicated in this delivery. Dataset provenance and licenses are
retained in the fixed transport. CPU-budget training naturally produces slightly
different update counts on different hardware; seeds alone do not make timings
or selected checkpoints portable.

To render the saved figures after restoring saved evidence:

```sh
MPLCONFIGDIR=/tmp/hcsn-r10-matplotlib python3 figures/make_figures.py
```

## Measurement and scientific limits

Native task costs are declared utility units. Native whole-run timings include
startup, validation, real execution and task publication but exclude earlier
payload/table preparation and training. AV complete child CPU includes startup,
data loads, training, validation, test and writes. The value runner's historical
`end_to_end` field has a narrower function-level scope, documented in its report.
Partial affine FLOPs, task ticks, CPU seconds and joules are never equated.

The AV test cohort has been used historically. The follow-up is exploratory and
changes a training package, not only one hyperparameter. No natural long-video,
causal online media, trainable frontend, large-model pretraining, new traditional
SNN/Transformer comparison, GPU throughput or measured-energy claim is made.

The next scientific acceptance is a **single shared content/probability/value
transition kernel** used in teacher, differentiation and native execution, with
the analytic state causally changing reads before their cost is incurred. That
claim is still open; it is not implied by the completed component checks.
