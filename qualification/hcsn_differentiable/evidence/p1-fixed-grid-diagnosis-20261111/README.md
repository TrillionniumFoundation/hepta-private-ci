# P1 integration and fixed-grid mechanism diagnosis

This entry binds two distinct results: execution of the complete finite-schedule
test module after integrating the exact #5878/#5910 fixes, and execution of the
previously frozen 48-case scalar mechanism study. Neither result grants whole
training-domain accuracy, sufficient training, scientific benefit or adoption.

## Exact-source finite-oracle integration

The new candidate starts from #5920 commit
`4ed61beacd9e8cf08cd1f7f8c938b75d747149e4`. The following three complete files
were reconciled against the remote Git blobs, preserving the original finite
oracle thresholds and historical source identities:

| File | Source | Exact Git blob |
| --- | --- | --- |
| `training_domain_finite.py` | #5910 | `8bbb1fde0f9e1ab08a16257c4bb598b114209210` |
| `tests/test_training_domain_finite.py` | #5910 | `2ac24a7d05b17f9acf4cf15cc88ecde2ae382fbe` |
| `TRAINING_DOMAIN.md` | #5878 | `cfb5890e05f55fbb59a0f5a93843568ea7b825b6` |

These changes reject non-finite or misaligned comparison vectors, reject
trainable/coerced time intervals, bound infinite iterables, and expose ordinary
relative error alongside the existing scaled error. Earlier C2 traces retain
their original source binding.

On heptaruntime `ai395`, the complete
`qualification.hcsn_differentiable.tests.test_training_domain_finite` module
passed **6/6 tests**, with no skips or errors. This closes the earlier gap where
only extracted helpers and syntax had been exercised. All eight transitive
local import files were transported with their original bytes and independently
hashed before and after execution. This was a complete test-module execution,
not a whole-repository CI run.

The native job `1a1c8f96154-135c4-34a` published a confirmed, durable successful
terminal result, exit code zero, with complete stdout/stderr. Runtime:
Python 3.14.4, Torch 2.13.0+rocm10.0.0, NumPy 2.5.2 and mpmath 1.3.0. Tensors
ran on CPU with one Torch thread. The timed runner section used 2.2084 seconds
wall time and 1.0578 seconds CPU time, with 705,904,640 bytes process peak RSS.
Timing includes Torch/NumPy/mpmath imports and the tests; interpreter startup,
standard-library imports, the remote launcher and tool transport are outside
that timed section. This is not a complete experiment resource bill.

Original [stdout](native-finite/stdout.txt), [status](native-finite/status.json),
[read receipt](native-finite/read.json), [runner](native-finite/runner.py),
[source capsule](native-finite/SOURCE.zip), and
[source manifest](native-finite/SOURCE-MANIFEST.json) are retained.
[The parsed result](native-finite/native.json) is decoded from the final JSON
object in that original stdout, rather than presented as a separate readback
of the native `RESULT.json` file. [Collection metadata](COLLECTION.json) records
this distinction and the current source comparison.

Reproduce from the repository root with the stated dependencies:

```sh
python -m unittest -v qualification.hcsn_differentiable.tests.test_training_domain_finite
```

## Fixed 48-case mechanism study

The historical [plan](inputs/FOLLOWUP-PLAN.json) and its
`execution_authorized=false` design snapshot were left byte-for-byte unchanged.
The user's current instruction to proceed authorized this execution. There
were 42 free-Gaussian adjacent-cell comparisons, four isolated phase cases and
two analytic tail moments. All 48 were executed, with no retries, no network,
no trained model and no posterior data.

The first execution is preserved as [original result](original/RESULT.json)
and [original runner](original/runner.py). A portable runner then performed one
independent reproducibility replay; all input/node identities and all 48 numeric
records matched exactly. See [replay](REPLAY.json) and
[comparison](REPLAY-COMPARISON.json). Both execution costs are retained; the
replay is not additional independent scientific evidence.

Selected observations for width 0.01875, 32 Gauss nodes and sigma 0.35:

| Observation | Result |
| --- | --- |
| Free adjacent-cell probability at time `1e-7` | Exact scalar `0.002354923687`; fixed nodes `0.002358114132`; relative difference `0.13548%` |
| Same scalar at time `8e-7` | Relative difference `1.40258e-6` |
| Deep small-time case `5.37134e-13` | Exact scalar `5.45781e-6`; fixed-node sum underflows to zero |
| Initial remaining-time law uniform on `[0.1875, 0.2]`, observed at `0.1` | Physical release probability zero; repeated phase projections give `1.52588e-5` to `0.00634402` across the four prescribed step sizes |
| Two tails with equal stored mass, separated by shift one | Continuum discounted-hit moments `0.00836229` and `0.00351518`; ratio `0.420361` |

These results separate source quadrature, phase reprojection and tail-shape
loss. They do not assign shares of the original 12 perpetual tiny-gap failures
to these mechanisms, test the full killed/reset operator, or qualify the
independent finite-CTMC proposal. The latter's exact discrete semigroup does
not establish the continuum's rare-hit or deterministic-wait laws.

The first timed scalar section took 0.00997 seconds wall time and its process
peaked at 13,762,560 bytes RSS; the replay took 0.00892 seconds and 14,680,064
bytes. These timed sections exclude interpreter and standard-library startup.
Both used one worker with 120-second CPU/256-MiB address-space limits. FP64
underflow observations and non-certified roundoff diagnostics are reported
explicitly in each row.

Reproduce this Linux/POSIX diagnostic with the standard library only and a
new output path:

```sh
python qualification/hcsn_differentiable/evidence/p1-fixed-grid-diagnosis-20261111/run_fixed_grid_diagnosis.py --output /tmp/hcsn-fixed-grid-replay.json
```

## Remaining gates

P1 remains **HOLD** for complete training-trajectory coverage, relative rare
tails, full long-sequence renewal/age semantics and accepted-domain gradients.
P2 adequate six-fit terminal/replay and full-cost scientific comparison, P3
QVI value, P4 real asynchronous benefit, P5 hardware and ordinary adoption
remain separate obligations. No previous failed or unknown result was changed.

[MANIFEST.json](MANIFEST.json) binds this evidence bundle. The ordinary
`qualification.hcsn_differentiable.evidence_chain` verifier checks its hashes,
ZIP member CRCs and relative documentation links.
