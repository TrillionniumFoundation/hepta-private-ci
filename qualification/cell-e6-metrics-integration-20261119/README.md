# E6 terminal-accounting integration into the joint candidate

The joint candidate at `325218ec2e5f085637e78e192bf188842e51fad5` still accepted an engineering terminal status without retained C use and cold replay. This integrates the two reviewed blobs from #6709 into that candidate and verifies the resulting Python control path.

## Integrated source

- Product source commit: `0bdf65445f9bbefba2c45dc3e611dd36386a1456`.
- Product source tree: `b07d9cfd5742db8d8f4f5feff8287d0f6b6592fe`.
- Parent: `325218ec2e5f085637e78e192bf188842e51fad5`.
- Imported fix: `773f25e53504790c74364aa3b1606ed51853df32`.
- `source_metrics_v3.py`: Git blob `04c556c5831ba2a01341404f15882020a68ff956`.
- `test_source_metrics_v3.py`: Git blob `3bd61299f923e1f3ce2f80d92780991dfab4434e`.

Both source files are byte-identical to #6709. Terminal ADOPTED/NO_UPDATE reports require nonempty selected-model C use, verifiable business observations (a verified failure is allowed), and a consistent cold-process replay. Incomplete outcomes remain incomplete.

## Actual verification

| Retained attempt | Result |
| --- | --- |
| Old production code + imported regression tests | 7 tests; 1 expected failure: absent C use did not raise |
| Integrated source, first sparse snapshot | 114 tests; 1 setup error: original `specs-open.json` absent |
| Same integrated source, original fixture restored | 114 tests / 18 modules; 0 failures, 0 errors, 0 skips |

The complete run took 6.777 seconds inside unittest, 7.227881317 seconds of measured outer wall time, and 7.426839 seconds of reaped child CPU. These are separate measurements, not additive cost estimates. All source and test bytes remained unchanged during the final run.

The final fixture was fetched from the same frozen upstream commit and checked by Git blob identity. No test or assertion was changed to resolve the setup error. Both earlier attempts and their full raw outputs are retained.

The checks ran on Linux, Python 3.12.14, in an isolated dependency snapshot. `SOURCE_MANIFEST.complete.json` binds all 66 source/fixture files by Git blob, SHA-256 and length. This avoids consuming the desktop model experiment's CPU budget.

## Replay

From the repository root, use a new output directory:

```sh
python3 qualification/cell-e6-metrics-integration-20261119/run_controls.py --output /tmp/e6-metrics-integration-replay
```

The runner verifies the source manifest before execution, invokes the same explicit 18-module unittest list, retains raw outputs and measured process costs, and checks source immutability afterward. NumPy is needed by the existing controls.

## Evidence scope

This closes propagation of the reviewed accounting fix into the joint candidate. Research model calls, research training updates and original native E6 executions in this verification are all zero. Original NoUpdate/Adopt owner execution, fresh C/D, FinalUse, settlement and all existing scientific gates retain their own evidence and status.

`SOURCE_BINDING.json` associates the tested file set with the exact product commit. `ARTIFACTS.json` binds every retained verification file. The existing CURRENT and historical results are preserved.

