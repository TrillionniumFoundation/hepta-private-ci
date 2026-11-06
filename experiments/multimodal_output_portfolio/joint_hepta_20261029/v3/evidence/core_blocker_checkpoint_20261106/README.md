# Core review and failure evidence snapshot, v3

This bundle contains 210 source and evidence files with 22,453,495 original bytes under `round3_core_ci`. It preserves candidate preimages/postimages, patches, first verification receipts, historical unapproved directions, original d3 and #5011 logs, source-bound #5017 failure excerpts, the 38-file auth implementation audit, and the first-party metadata fixture candidate. Runtime failures remain distinct from source, formatter, and patch checks.

The compressed archive bytes are unchanged from the retained v1/v2 package. The three repository shards are raw binary, with sizes 450,000, 450,000, and 84,160 bytes. Their concatenation is the 984,160-byte xz tar whose SHA-256 is `600be6b45287dcbf20a80d0626ca815905d8155febedf4e6f2af33ad9b0d381e`. Do not base64-decode these shard files. Connector upload may use base64 solely as a transport encoding.

Run `python restore.py /path/to/bundle /path/to/fresh-restoration`. The output parent must already exist, and the output directory must not exist or be inside the bundle. The restorer pins the INDEX SHA-256 in its source, explicitly checks every shard, checks the exact unique regular-file member set and safe canonical paths, verifies all source hashes and modes before writing, and restores only ordinary file permission bits. It uses explicit errors rather than assertions, so Python optimization does not disable its checks. It neither extracts links nor executes restored files.

The restorer writes only the requested fresh output directory and prints its result to stdout. It never modifies this bundle or writes a verification receipt into it. The actual v3 restoration receipt is a separate artifact, `round3_core_evidence_pack_v3_verification.json`, which also binds hashes of every input-bundle file before and after that one successful restoration.

Publish the six files listed by `INDEX.json` under `publish_files`, plus the separately supplied v3 verification receipt. The v1/v2 bundles remain local history. V1's first checker confused full stat modes with permission bits; v2 corrected that comparison but wrote a receipt into its input bundle. Both limitations are retained in the review record. V3 preserves the same archived data and makes restoration read-only with respect to the input bundle.

Local candidate filesystem modes describe the scratch evidence snapshot. Publication of repository source still preserves each path's Git mode from the current remote tree. A successful archive restoration is not evidence that native compilation or integration tests passed.
