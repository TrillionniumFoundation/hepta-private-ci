# Raw machine evidence archives

Eleven machine-generated log or metadata files are stored as deterministic gzip archives. Their original bytes, original Git blob identities, archive hashes and locations are listed in `RAW_EVIDENCE_ARCHIVE_MAP.json`. No spelling replacements have been made inside the evidence, and the repository spell-check policy is unchanged.

To resolve an older evidence manifest, find its original path in the map, decompress the corresponding archive with `gzip.decompress`, and compare the bytes with the original SHA256 and length. The first nine original paths are also available at source commit `6396bc013fdb16a955cced8a746e27279311361c`. The remaining two members were recovered from Actions artifact `12949765079`; the complete original ZIP is retained in the vendor recovery evidence. Existing earlier `.gz` files represent different log snapshots and have not been overwritten.

`RAW_EVIDENCE_ARCHIVE_VERIFICATION.json` records eleven byte-exact round trips. This is an archival check; it does not claim that the historical tests ran on the current source.
