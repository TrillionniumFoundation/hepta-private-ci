# Restore original closed publication records

Verify the ZIP size/SHA and CRC, then every member path, byte count and SHA from
MANIFEST.json before extracting to a new directory. Original COMPLETE.json
retains its earlier PUSHED_PENDING_API_VERIFICATION status. The later saved
Draft-publication record contains the completed API checks. Neither is rewritten.

The static summary compares those saved records. It does not perform new API
calls, Git mutations, PR operations, merges or deployment.
