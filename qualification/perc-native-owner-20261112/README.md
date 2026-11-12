# PERC native owner and diagnostic head qualification

The previous native PERC probe stopped at PerceptionCellEncoderV1. This
increment feeds its original Q24 output through actual bounded Rust linear-head
arithmetic, infer_cell_with_clock, the existing sparse decision mechanism, and
CellOwnerJournalV1 with FileAnchorWitnessStore. The libraries are unchanged from
2ec44e234a7164807f41af3a79e795dd71efa179.

## Observed qualification

REPORT_FIXTURE.json records 13 separate native process invocations on the
existing hand-authored interoperability fixture. This is a mechanism test,
not a new real task, an independent source, or a model-quality benchmark.

- Two head executions matched an independent Python integer arithmetic oracle.
- Three completed cold replays performed no encoding, inference or inference
  readback; the complete exported decision remained unchanged.
- An intentionally lost acknowledgement recovered the original persisted
  inference result without repeating the head computation.
- Missing and changed original inference receipts retained pending admission.
- Changed source bytes, changed head bytes, a self-consistently rebound source
  frontier, and journal rollback with the separate witness intact were rejected.
- A read-only call without an original admission refused new computation, even
  after both local journals were reset. This last control is a read-only API
  guarantee, not a general guarantee against correlated storage rollback.

The second qualification run adds the final read-only control to the same
fixture; it is not additional independent task evidence. Both original runs
and all three build attempts are retained in the archive. The first failed at
offline dependency resolution, the second at macro expansion, and the third
compiled successfully. Neither failed build reached native qualification.

## Reproduce

Build the standalone probe from an exact selected library tree:

    python scripts/perc1_native_owner_probe.py \
      --repo "$PWD" --build-dir /tmp/perc-native-build \
      --source-ref 2ec44e234a7164807f41af3a79e795dd71efa179

The default requires a populated offline Cargo cache. The --online option
explicitly permits ordinary Cargo dependency retrieval. The --cargo and --rustc
options can name selected toolchain executables. Build records retain all native
source pins, generated main source digest, lockfile, logs and binary digest.

The executable uses the same expected-input schema as the existing native
Cell encoder probe. Supply exact original wire bytes, the actor's matching
raster or byte source, and the original scope/encoder/source bindings:

    python scripts/perc1_native_owner_qualification.py \
      --binary /tmp/perc-native-build/target/debug/perc1-native-cell-probe \
      --wire wire.json --raster raster.rgb --expected expected.json \
      --output /tmp/perc-owner-qualification \
      --input-classification captured_source

The classification flag is a caller declaration; the capture evidence must
establish actual provenance separately. The runner generates an explicitly
hand-authored diagnostic head and compares its actual native outputs with an
independent arithmetic oracle. It does not substitute that head for the trained
semantic MLP or claim equivalence between the two.

## Boundaries

- Scientific status remains HOLD; no terminal task benefit or production adoption.
- No production daemon startup, enrolled authority owner, independent custody,
  distributed fencing, or cross-boot migration qualification.
- The calibration values are fixed qualification fixtures, not empirical
  calibration or OOD measurements.
- The separate journal and witness are local files in one fault domain.
  Hashes establish byte consistency, not an independent origin attestation.
- The head and source files are retained under the local operator. The native
  observation limits, existing state owner guards and inference contracts are
  unchanged; exact full-document sidecars remain a separate capture channel.
- Head latency uses Instant; native allocation counts describe owned numeric
  vectors. Command wall time is retained separately. No CPU, process RSS, energy
  or provider billing qualification is claimed.
- The state clock uses Linux /proc/uptime at centisecond resolution with an
  exact boot-ID binding. The probe refuses a different boot rather than
  silently translating persisted deadlines.
- These are standalone mechanism runs, not the full repository test suite.
