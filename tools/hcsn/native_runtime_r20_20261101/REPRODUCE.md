# Reproduction and retained-checkpoint replay

Use the pinned repository source, Python 3.12, NumPy 2.3.5, SciPy 1.17.0 and the recorded Linux Rust artifact. The process-death harness uses Linux `wait4`, `waitid`, SIGKILL, file locks, directory fsync and local IPv4 sockets. Exact historical replay also needs a compatible Linux x86-64 dynamic-link environment. A constructed-operator bit change is rejected by the model identity rather than silently accepted.

First restore the raw evidence as directed by `TRANSPORT.md`, then restore the exact executable artifacts:

```sh
python tools/hcsn/native_runtime_r20_20261101/restore_binaries.py --destination /tmp/hcsn-r20-binaries --restore-evidence-aliases
```

The formal executable is the SHA256-named file ending in `b30befcb76f00533029c60ce7a430a2b057bc152107625d7a5a4be3cd16f2798`. Read-only record review can use relocated verified binary bytes:

```sh
python -m tools.hcsn.native_runtime_r20_20261101.audit_restored tools/hcsn/native_runtime_r20_20261101/confirmation01 --binary-directory /tmp/hcsn-r20-binaries --output /tmp/hcsn-r20-record-review.json
```

The adapter only resolves historical ELF paths to byte-identical restored files. It calls the unchanged frozen `audit_records.py`; it does not modify records, comparisons, reference values or that source file. Both adapter and original checker identities are recorded. `RESTORED_ARTIFACT_RECORD_AUDIT.json` preserves the successful delivery check.

`BINARY_RESUME.md` gives an actual retained three-parameter financial pending-action checkpoint replay, including a real new owner/provider process pair and byte-exact comparison with uninterrupted execution. That replay uses an already published world and is not additional independent confirmation evidence.

For a complete deterministic engineering replay, choose a new output directory:

```sh
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 taskset -c 0-6 python -m tools.hcsn.native_runtime_r20_20261101.independentcheck --binary /tmp/hcsn-r20-binaries/b30befcb76f00533029c60ce7a430a2b057bc152107625d7a5a4be3cd16f2798 --output /tmp/hcsn-r20-fresh-replay --namespace 20110471 --worlds 16 --financial-worlds 4
```

The formal namespace enforces the published 17-file source freeze and 16+4 world counts. Reusing it is a reproduction of the existing confirmation, not fresh confirmation data. The executable itself generates no oracle successor inputs. The Python reference constructs provider observations and independent expected posteriors outside the owner; only actual provider receipts reach the Rust update.

Rebuilding with `rustc --edition=2024 -D warnings .../main.rs -o NEW_BINARY` creates a separately identified artifact. It can generate new public PLAN identities through `identify MODEL`, but it must not bypass the identity check to resume a checkpoint from another artifact. `BUILD_FROZEN.json` records the exact tested build, hashes, and source publication. No Cargo dependencies or downloads are needed for this standalone program.

The raw zero-evidence control contains a real provider fee25 and an unapplied owner pending index. Review that expense separately; the failed operation is not counted as a successful, free query. All broad production, authentication, energy and analytic-core efficacy gates remain separate.
