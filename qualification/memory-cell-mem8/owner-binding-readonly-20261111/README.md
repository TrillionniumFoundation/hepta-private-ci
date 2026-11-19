# Original MEM owner binding evidence

This package preserves the bounded, read-only owner binding review against
source `0c32926cfec58d986477fc72ba3a4787ab75fde9`, plus the nonsecret observations
used for its deployment conclusions. It does not contain or establish an
original runtime authority, source verifier, final-use grant or recovered effect.

## Contents and provenance

- `OWNER_BINDINGS_REVIEW.md` records the existing interfaces, remaining concrete
  deployment inputs and execution order. Its source links are pinned to the
  reviewed commit. Original-owner cold recovery and scientific adoption remain
  unqualified.
- `OWNER_RUNTIME_INVENTORY.json` and `OWNER_RUNTIME_INVENTORY_V2.json` are complete,
  unchanged metadata reports observed on desktop at 03:08:24 and 03:11:21 UTC on
  2026-11-11. They contain directory names, selected file metadata, service
  status/path fields and socket rows. `METADATA_READBACK.json` binds their full
  byte counts and hashes. V2 explicitly did not read file contents.
- `PUBLIC_OWNER_FIELDS.json` is the separate, restricted extraction from three
  already identified public JSON files. It records only role names/test-only
  flags, reported cleanup disposition/time and the startup release flag, plus
  source file sizes/hashes. The five old roles are test roles; the cleanup is a
  receipt observation, not a fresh inspection or erasure proof. No startup date
  is inferred from the release flag.
- `PUBLIC_OWNER_FIELDS_TRANSPORT.json` and `read_public_owner_fields.py` preserve
  the completed extraction identity and exact bounded script. The script is
  evidence and is not run by bundle verification.
- `MANIFEST.json` is the unchanged original seven-file inventory.
  `PACKAGE_MANIFEST.json` indexes every other member in this package by byte
  count, SHA256 and Git blob ID. `verify_bundle.py` checks extracted files or a
  supplied tar archive without executing the collector.

No private-key bytes, authentication values, service environment contents,
protected runtime-directory contents or full public-role source files are
included. Names of services, paths and configuration fields are metadata, not
credentials. The package uses an explicit file allowlist and includes no files
from surrounding runtime or build directories.

## Verify

After safe extraction, run `python3 -B verify_bundle.py`. To check the archive
directly, run `python3 -B verify_bundle.py /path/to/owner-binding-review-20261111.tar.xz`.
The latter also rejects unexpected members, duplicate paths, nonregular entries
and unsafe paths. The externally published archive SHA256 binds the package
manifest itself; that manifest deliberately does not hash itself.

The bundle contains no new inference call, external effect or native test run.
References to earlier exact-source software tests and the recovered MEM6 archive
remain separate evidence. Matching archive bytes and passing fixture tests do
not authenticate the missing original owner or independent issuer.
