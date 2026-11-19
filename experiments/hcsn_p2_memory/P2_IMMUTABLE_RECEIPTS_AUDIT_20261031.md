# P2 v3 immutable original-result receipts (2026-10-31)

**Scope:** research-only, DENY_ALL, NO_GO. Branch stacked on #4506 exact HEAD a93af40fc59732a8c1ed36ef1878eed7c59db658, not the competing #4505 branch. All v1/v2 original raw records, unfavorable OOD scores and training code are byte-identical to parent. No production/CI/Rust/GPU authority changes.

## Why

The old v2 training entrypoint writes each original JSON record with Path.write_text, which replaces an existing path. PR #4505 identified at least three post-stdout path content/digest changes. This tool prevents **future** registered records from being silently replaced, but does **not** repair provenance of historical ambiguous files or turn negative scientific results into wins.

## New implementation

- immutable_trial_receipts.py: validate fixed 12-arm schema; create a canonical JSON envelope including the original record and its SHA-256, write in an unpredictable same-directory temporary file with O_CREAT|O_EXCL / O_NOFOLLOW, fsync the complete file, publish with create-only hardlink, fsync the directory and unlink the old staging name. A duplicate task/seed/arm is rejected even when content matches.
- Registered run keys are exactly task in {copy,mqar4}, seeds 2/3/4, and aggregate_count/physical_event_timestamp. Each envelope explicitly keeps production_activation=false and scientific_gate_closed=false.
- Seal only after all 12 records are present and pass strict independent per-record readback. Seal itself is a create-only canonical manifest binding all 12 individual file SHA-256 hashes and original payload hashes. Missing, unexpected, mutated, symlinked or staged data cannot silently pass.
- An explicit post-crash recover_stages(root, quiescent=True) is required after stopping all writers. If a stage already has the final hardlink, verify binding and remove extra staged hardlink; if there is no final link, **quarantine** the uncommitted stage rather than converting it to a completed trial.
- timed_cpu_matched_v3_immutable.py adds an **opt-in** CLI wrapping unchanged v2 run() in memory and publishing directly with readback. It checks for an existing or sealed result before spending the CPU budget and never writes a replaceable intermediate JSON.

## Reproduce local filesystem tests

    python -m unittest -v experiments.hcsn_p2_memory.test_immutable_trial_receipts experiments.hcsn_p2_memory.test_timed_cpu_matched_v3_immutable

Local Python 3.11 Linux POSIX filesystem: **16/16 methods PASS**, no skips, including four simultaneous new-process writers of a single key (exactly one succeeds); real separate-process os._exit after data fsync and after create-only link; explicit stage quarantine/recovery; 12-item lossless seal verified from another Python process; tampering, duplicates and wrong authority rejected. A second local test copied all four files to a repository-style experiments/hcsn_p2_memory/ package and re-ran **16/16 PASS** to catch package-relative subprocess errors.

These are **filesystem and mocked-training smoke tests**, not 12 actual new training jobs or production host power-loss testing; a hard crash test with os._exit is NOT equivalent to power loss. SHA-256 is integrity only, not authentication. This does not independently certify upstream v2 training metrics or provenance.

Locally executed, remote Git blob SHA1 matched exactly:
- immutable_trial_receipts.py: c5bc0c318f58b52f4fd32f03b15e721b3932aeeb
- test_immutable_trial_receipts.py: 7d3d1d90fe2016bdbbdf1e95f08b8392c3a633a6
- timed_cpu_matched_v3_immutable.py: 1a959669a9908489887b9833b297cd7b915bcef3
- test_timed_cpu_matched_v3_immutable.py: 11ec3252dc1893d77ab2fa80a48db2c8bb160e0f

## Opt-in commands

    python -m experiments.hcsn_p2_memory.timed_cpu_matched_v3_immutable run --task copy --seed 2 --arm aggregate_count --archive /path/to/new_store
    python -m experiments.hcsn_p2_memory.timed_cpu_matched_v3_immutable seal --archive /path/to/new_store
    python -m experiments.hcsn_p2_memory.timed_cpu_matched_v3_immutable verify --archive /path/to/new_store
    python -m experiments.hcsn_p2_memory.timed_cpu_matched_v3_immutable recover --archive /path/to/new_store --quiescent

No real new v3 CPU training was executed in this increment. Any future run must start with a **new and separate** archive directory and record prospective original raw output identities, ensuring historical v2 source/digests are never rewritten.

## Remaining blockers

P0 physical financial continuum/global HX and actual interval input guarantees remain OPEN. P1 causal matched mechanism advantage remains OPEN. P2 full long memory, independent negative-transfer reversal and **production-durable authenticated host recovery** remain OPEN despite these filesystem receipts. P3 four real encoders, P4 Rust/GPU 64-4096 Cell/Joules remain OPEN; P5 Hybrid scaling BLOCKED. all_scientific_blockers_closed=false and production_activation=false.
