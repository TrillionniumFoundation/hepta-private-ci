# MemoryCell INT8 finite engineering screen — source-only recovery (2026-11-04)

This inactive archival projection preserves **the exact twelve preregistration package members** from the ChatGPT Library archive `memorycell-quantization-preregistered-code-20261104.zip`. No current product source, model authority, runtime implementation, CI configuration, or production policy is changed.

## Original identities

- Original preregistration ZIP SHA-256: `03d7c8af103040458a1035e1e5f2bfbf0c3b3428242f870bafd510161d4439bd`, 30,464 bytes.
- Follow-up publication ZIP SHA-256: `5d5f1359780d88d07b01b4b65248d47905228f0c4c83a2ce358494c6ef3676ec`, 35,204 bytes.
- The follow-up publication package contains byte-identical copies of the ten executed core/test/fixture/dependency files (see its `release_manifest.json` retained in the original Library). This recovery does **not** publish post-run aggregates, experiment logs, model files, installations, weights, or authority records.
- Original member SHA-256 values are specified in `seal.json`. All 12 exact Git Blob SHA values were checked against the original ZIP bytes and individually fetched from the remote repository Git object database before reuse. `PROTOCOL.md` and the original `seal.json` are preregistration versions, not edited post-run versions.

## Offline verification of recovered source

From this directory:

```sh
PYTHONDONTWRITEBYTECODE=1 python -B -m unittest -v test_protocol
PYTHONDONTWRITEBYTECODE=1 python -B -c 'from common import verify_seal; print(verify_seal())'
```

The source is intentionally held under `library-recovery/`, not an active deployment path. On a bounded isolated local standard-library run, all **23/23** existing protocol tests passed; no model, PyTorch, weights, network, download, or actual INT8 runtime was invoked. The tests do not prove a deployment-ready quantization benefit. The original follow-up publication reported numerical qualification failure; this code recovery does not override it.

Before any live trial, the original protocol requires independently authorized model asset acquisition, an admitted runtime manifest, prospective policy and fixed gates. DRAFT / RESEARCH_ONLY / DENY_ALL; this is archival preservation, not a production grant. Original Library files were not deleted.
