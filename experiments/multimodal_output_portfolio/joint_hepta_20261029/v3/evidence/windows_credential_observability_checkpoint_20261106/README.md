# Windows credential observability evidence supplement

This packet preserves 44 selected files and 230,835 original bytes. Its 1 binary gzip parts are each at most 450,000 bytes.

Run `python -B restore.py /absolute/path/to/a-new-directory` with Python 3.12 or later. The destination must not exist. The fixed reader verifies the bounded gzip segments, archive hashes, exact member set and every file hash before writing inert 0644 files. No recovered source executes.

Fixed INDEX SHA-256: `06431da8fbc1907cb29d3153e4009749c28055fa17114685ccdf32d64ff536c6`. Only the approved reader's index seal changed. ROUNDTRIP.json records actual exact restoration and nine negative checks.

After restoration, read `round3_native/credential_observability_checkpoint_inputs/HISTORY.md`. This appendix preserves A3/B3 and the third run's real first-gate scanner refusal. The account probe and explicit cleanup were not reached. The earlier #5102 account and cleanup state remain UNKNOWN. No native probe pass or historical root cause is claimed.

Original GHA logs are excluded; the original upload gate did not accept them. Only fixed approved observations and source/log identities are retained. No excluded raw log can be reconstructed from this packet. All earlier frozen packets remain unchanged.
