# Native blocker evidence checkpoint

This packet preserves 182 original files and 64,564,204 bytes. It contains 8 independent binary gzip parts, each at most 450,000 bytes. All source files restore as inert regular data; no source is executed.

Run `python -B restore.py /absolute/path/to/a-new-directory` with Python 3.12 or later. The destination must not already exist. The script first verifies the fixed index, every gzip part, the reconstructed tar.xz and tar, all member paths, sizes and hashes. It then writes 0644 regular files. Original permission bits and full stat modes are separate evidence fields.

Fixed INDEX SHA-256: `c176d46a659cc6f6c174ea11eaf27344cc75c6082b3fe9f982ec17a24e9de3d1`.

After restoration, start with `round3_native/checkpoint_inputs/HISTORY.md`, the publication ledgers, the raw-log catalog and `source_checkout_trees.json`. Original candidate manifests are historical; later actual execution evidence is separate. Units 07 and 18 publication mistakes, the remaining unit 14 anchor failure and unit 17 omitted configuration test are retained.

The complete native repository has not passed in this snapshot. Cached, skipped, cancelled and queued results must not be counted as newly executed acceptance. Internal static review is not external audit. The package excludes Git-recoverable full source trees and large tool binaries.

`ROUNDTRIP.json` records an actual full restore, exact membership and byte equality, inert modes, and negative probes. Independent gzip headers keep the existing spell checker from interpreting random interior compression bytes as prose; no spell-check policy is changed.
