# Exact executable retention and checkpoint replay

Model identity includes the actual executable's fingerprint. Rebuilding from source is a separate artifact and may produce a new identity. The exact tested Linux ELF is therefore retained, together with historical engineering and altered-artifact control executables. Four distinct byte strings are deduplicated into twelve gzip transport parts, each at most 450,000 bytes. These are research artifacts, not production release authorization.

Restore raw evidence first as described in the evidence transport instructions, then restore exact binaries from the repository root:

```sh
python tools/hcsn/native_runtime_r20_20261101/restore_binaries.py --destination /tmp/hcsn-r20-binaries --restore-evidence-aliases
```

The restorer verifies each part, gzip and ELF SHA256 and refuses symlinks or an existing different file. It does not execute a binary. The formal artifact is:

`/tmp/hcsn-r20-binaries/b30befcb76f00533029c60ce7a430a2b057bc152107625d7a5a4be3cd16f2798`

The optional aliases restore exact ELF inputs beneath the original negative-case evidence paths; historical absolute `/tmp` paths are provenance, not restore destinations. `BINARY_ARTIFACTS.json` records all original paths and hashes.

For an actual native-financial paid-pending checkpoint, run the following command with a new output directory:

```sh
python tools/hcsn/native_runtime_r20_20261101/replay_retained_checkpoint.py --binary /tmp/hcsn-r20-binaries/b30befcb76f00533029c60ce7a430a2b057bc152107625d7a5a4be3cd16f2798 --case tools/hcsn/native_runtime_r20_20261101/confirmation01/cases/16_02 --expected tools/hcsn/native_runtime_r20_20261101/confirmation01/cases/16_00 --output /tmp/hcsn-r20-paid-pending-replay
```

The script copies the retained owner/provider crash snapshots, starts a real fresh loopback provider, resumes the real Rust owner, and compares both final durable state files byte for byte with uninterrupted execution. The selected model file contains only three financial parameters. Its generator, prior, propagation and Bayesian successors are computed in Rust. The script writes `REPLAY.json` and process outputs; it never supplies an oracle successor to the runtime.

`BINARY_ROUNDTRIP.json` records exact restoration of all four artifacts and matching read-only `identify` results after relocating the formal executable for both model profiles. `BINARY_CHECKPOINT_REPLAY.json` records the actual retained-checkpoint replay performed during delivery verification. These are engineering replays of existing data, not additional independent confirmation worlds. Cross-artifact migration, authenticated transport and production model admission remain open.
