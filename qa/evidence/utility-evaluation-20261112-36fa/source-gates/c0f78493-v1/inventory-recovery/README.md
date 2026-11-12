# c0f original inventory byte recovery

The source-closure run on exact c0f78493 remains FAILED with its original 600-second timeout. This package preserves the identical before/after source inventories from that run; it is not another run or another full on-site filesystem observation.

The original retained manifest fixes both raw inventories at 5,474,911 bytes and SHA256 cdb6cea4f3142702681a20476db2a078a08d7b3b981bbc1ceb568c886fe3aa57. Rebuilding the original deterministic encoding from the independently verified full native metadata map and immutable driver produced exactly that digest, all five original gzip part sizes/digests/Git object IDs, and all four actually observed fixed-version H chunks. The raw parts have been created as immutable Git objects; every base64 companion and every text record was fetched in full and compared exactly.

For each original inventory, concatenate part0000 through part0004 in order, gzip-decompress, then check the raw byte length and SHA256 in PLACEMENT.json. The corresponding base64 companions can be decoded before the same procedure when a client cannot read binary Git blobs. github_fetch_blob returned UnicodeDecodeError when asked to decode the first raw gzip part as UTF-8; this limitation is recorded instead of claiming a direct binary readback.

INVENTORY_EXACT_RECOVERY.json records the checks and observed source identities. The original local helper and its auxiliary trailing-newline assertion failure are retained alongside the narrowly corrected v2 helper. Both preserve original gate results unchanged. The four observed-chunks files contain exact H native response text without an added trailing newline. Existing original raw logs, runner JSON, and final gate status remain separate records.
