# Direct-host continuation engineering evidence

**Disposition: `no-update`.** These files establish a bounded engineering
execution, not a scientific gain, dedicated Codex deployment or production
activation. The directory uses the client-session date 2026-11-04; execution
occurred on 2026-11-05 UTC. The source parent is
`18dac3ccd30317893ad922792c12400390522f00`.

## What actually ran

The authenticated `desktop` host ran a new isolated task directory with Python
3.12.3, Torch 2.6.0+cpu, NumPy 2.2.6, Pillow 11.3.0 and Rust 1.95.0. CUDA was
unavailable to this Torch build. No shared environment was upgraded.

| Record | Observed outcome |
| --- | --- |
| Rust formatting | Passed in 0.0299 seconds |
| Native compilation | Passed in 0.4346 seconds |
| Final contract suite | 35 tests passed; 8.350 seconds within unittest |
| Test subprocess elapsed time | 12.764618239 seconds |
| Retained fixture subprocess elapsed time | 5.498255133 seconds |
| Paired fixture | Two synthetic cases, four continuation branches plus STOP each, 10 actual PNG/text bundles |
| Native comparison | 78 features, four outputs, two rows; maximum absolute error 0.0 at absolute/relative tolerance 1e-10 |
| New-process reload | Exact initial-state inference after checkpoint reload and input re-encoding |
| Scientific confirmation / Codex deployment / production activation | All false |

`tests.stderr` is the complete successful unittest log, including executed
Torch/Rust parity. `RUN.json` records subprocess timings and binary/log hashes.
`SOURCE_MANIFEST.json` pins all 46 Python/Rust source files used by this run.
Its file hash differs from the canonical-JSON aggregate hash in `RUN.json`;
the latter hashes `json.dumps(manifest, sort_keys=True).encode()`.
The original 46 upstream source/data/document blobs are separately pinned in
`materialized_sources.json` and were verified byte-for-byte unchanged.

The final runtime job was `1a1a94a9565-fc05-33cf`. Native formatting/compilation
ran in the first attempt, `1a1a946ea6d-fc05-339e`, whose import failures are
retained under `first_attempt/`. Missing Pillow was then installed into the
isolated task dependency directory, and the complete suite was rerun. Only the
absolute task-root prefix in that failed log is redacted; its original and
published SHA-256 are recorded. The compiled source did not change between
those two attempts.

## Checkpoints and actual output bytes

`fixture_evidence.zip` contains the generated `generator.pt`, fitted
`continuation.json`, original public input, paired records, all 10 PNG/caption
bundles, and `RESULT.json`. Its 24 declared inner artifact hashes were verified
after transfer. No compiled executable is included; its digest is in RUN.json.

```
fixture_evidence.zip bytes: 1731479
SHA256: dd3b1d38f521ebe798c63b3e35417bf920598968460afe3bd90d5bcebede715f
generator.pt SHA256: 970aff6fc3031a172c5d0e5f71bc92b826c6ec4f86ae12f5cd20b32b7aa13492
continuation.json SHA256: 1c185a4f89d1bcd2f3b2b4f4a826c8824c60b3057c78702ae41b15b3fc159ed4
```

The public input consists of seeded random pixels and their complement. The
generator and observer are untrained; only the continuation head is fitted.
The two cases are not independent semantic-task evidence. The callback charges
measured transition, decode, media I/O and observation CPU/elapsed time under
an explicit fixture tariff. This is not complete production cost qualification:
encoder/policy/request overhead and other whole-episode expenses require the
outer ledger described in CONTINUATION.md. Parent CPU in RESULT.json excludes
child CPU; its wall duration includes the restore child. No GPU/energy or
arbitrary in-flight-session recovery claim is made.

## Source review and execution-location boundary

`independent_review.json` binds four reviewed source hashes, resolved code and
numerical findings, and assumptions that still need scientific validation.
`environment_review.json` records the execution-location audit. The current
Codex identity exposed no project environment ID; an empty cloud task list and
the unrelated historical self-hosted-runner job do not prove that the user's
configured environment does not exist. This direct-host result is not a
substitute for execution there.

The separate hosted workflow is an engineering reproduction entry point. Its
actual runs must be cited separately; static workflow review is not CI success.
The full seven-policy comparison, training/execution factorial, selected-action
calibration, semantic OOD rejection, prospective-world tests, and synchronized
audio/video execution remain open.
