# Library source custody — 2026-11-07

**Draft / HOLD / archive-only. No product integration or promotion.**

This isolated branch preserves 12 unique source byte identities from 13 visible Library path occurrences. It is scoped to `TrillionniumFoundation/hepta-private-ci`: the source modules reference `codex-rs`, `codex_hepta_learning_artifacts`, `codex-hepta-matrix-sdk`, and the `neuron_shared_encoder` package used by this repository.

The exact original target path is deliberately **not asserted** where the source does not prove it. All files are stored under `library-recovery/20261107/unresolved-direct-code/`; no existing product path is overwritten. The Rust files are preserved as snippets. The E4 receipt/shadow filenames are byte-identical and are represented once, with both Library file IDs recorded in the manifest.

## Reproduction

From this directory:

```sh
python3 -m py_compile *.py
python3 -m unittest -v test_dual_lock_resolution_gate.py test_matrix_security_preflight.py
```

Recorded isolated result: Python syntax/compile **11/11 PASS** and the two standalone unittest modules **23/23 PASS**. The E4, physical-token and strict-E2 tests were not executed because their package/sibling modules are not part of this bounded custody batch. The two Rust snippets were not compiled; one explicitly targets an old `runtime_tests.rs` baseline and the other has no verified insertion path.

## Byte identity and privacy

`SOURCE_CUSTODY.json` records every original Library path/file ID, exact byte length, SHA-256, Git Blob SHA-1, canonical archive path, duplicate mapping and repository-ownership basis. All 12 Git Blob objects were fetched from the private-ci object store and their UTF-8 byte lengths matched the independently hashed Library originals. The same blob IDs are now referenced by this Draft tree for durable path-level custody.

A narrow static screen found zero email/Gmail, PEM private-key, GitHub-token, AWS-key, bearer-token or home-path patterns. This is not a comprehensive privacy attestation. No archive, model weight, binary, raw log, personal address, or large evidence payload is included.

## Boundaries

- Source custody only; no assertion of product correctness, security acceptance, scientific validity, or production readiness.
- No original product source path is replaced or patched.
- No main merge, deployment, or security-gate relaxation.
- Original Library items remain retained. The dot-host original worktrees/unpushed commits and full Library inventory remain unverified.
- Authority remains **DENY_ALL**.
