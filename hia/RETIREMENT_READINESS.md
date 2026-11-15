# HIA whole-Codex retirement precheck

This is a **non-destructive, fail-closed prerequisite**, not an instruction to
delete Rust sources, merge a Draft PR, change the default compiler, or promote a
release. It cannot establish independently that an attestation is truthful.
Release owners must examine the raw original test evidence separately.

Run the deterministic synthetic controls:

```sh
python3 -m unittest discover -s scripts/ci -p test_hia_retirement_gate.py -v
```

Only after a complete release candidate has been independently qualified may
a release-specific evidence JSON be supplied:

```sh
python3 scripts/ci/check_hia_retirement_gate.py \
  --repo . --migration hia/migration.json \
  --evidence /path/to/source-bound-retirement-evidence.json
```

The command returns exit **1** and JSON `ready:false` if any required
condition is absent or false; exit **0** means the listed *metadata and
evidence-file identities* meet the contract. It performs no mutation.

Before retirement it requires the five whole-product migration flags,
`retirement.ready`, 15 complete named capabilities, all baseline Cargo
manifest identities (198 in the frozen inventory), and all candidate owners
marked `production_dispatch_migrated=true` and `retire_legacy=true`.
`legacy_source_retired` must still be **false** before this precheck.
No platform or module qualification can be borrowed from a different source
tree, skipped step, or feature configuration.

The evidence JSON is a new, separate candidate-specific artifact with
`schema: "codex.hia.retirement-evidence.v1"`, `source_revision` equal to the
actual checked-out Git commit, `source_tree` equal to its Git tree SHA, and
a `platforms` array containing the six explicit Linux GNU, macOS and
Windows MSVC architecture labels enumerated by the checker. It also contains
six entries of this form:

```json
{
  "index": 0,
  "requirement": "exact text of migration.retirement.requirements[0]",
  "status": "passed",
  "artifact": "qualification/path/to/independently-reviewed-evidence.json",
  "sha256": "64 lowercase hex digits of the exact artifact bytes"
}
```

All six numbered entries must match the unchanged retirement-requirement
strings in the source-bound migration file. The checker rejects duplicate
JSON keys, incomplete inventories, duplicate identities, missing artifacts,
symlinks, bad digests, and a dirty tracked checkout. It deliberately does not
generate a passing evidence file, bypass a failing CI job, or clean anything.

**Current state:** the published HIA branch still has pending and partial
capabilities, incomplete default/platform/workspace/performance qualifications,
and retained Rust implementation. The checker is therefore expected to
reject current retirement. The six file-hash checks are transport integrity
checks, **not** signatures, trusted provenance, or semantic proof of the claims.
Actual release approval and safe deletion require a separate independently
reviewed transaction with full rollback, licensing, packaging and recovery
checks. Preserve all historical negative observations.
