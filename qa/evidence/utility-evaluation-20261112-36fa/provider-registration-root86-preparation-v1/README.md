# Provider registration proposal for the fixed 86-path view

This is a preparation checkpoint. It does not qualify, activate or publish a source revision. The source base remains cc57c7198db6293ccca562253c42fffbe2a04633 and the exact input overlay is 3f7d40d4933669da33d2aef3491efb431c5771ae. That view covers 86 Rust paths and two prepared non-Rust paths: 43 Rust additions, 42 changed original Rust paths, and one Rust path restored to its original bytes. One old test helper filename is removed by the earlier overlay.

The packet changes 19 non-Rust paths: CALLERS, its exact size allowance, 15 existing QA files, one new QA module and its separately hashed source contract. The existing Root QA file uses the already prepared 8223265bdcea271661fd46d448943484a28d5703 preimage from the input overlay. Other existing source preimages are the fixed canonical bytes. Every before and after body is retained in SOURCE_PACKET.json.

## Registered and protected scope

The proposal has 621 boundary entries. It appends callers to 17 existing entries and adds 52 entries. All other fields of the original 569 entries remain unchanged. The 437 protected rows consist of the original 422 rows plus 15 new rows. Among the original rows, 401 raw blocks are identical and 21 explicitly follow changed source. All original forbidden arrays and raw required markers are preserved. Row 411 and the complete restored Selection Remote source remain identical. Repeated paths are not deduplicated.

The old QA inventory remains 63 files and 590 methods. There are 587 byte-identical methods and three explicit method changes: two methods migrate three actual code markers, and one preserves the original 28-row slice at [541:569] while checking the new 621-row complete inventory. No old method or assertion is removed. The associated expected caller constants and five actual scope digests follow the fixed source.

The new QA module contains 14 prepared methods, 41 production paths, 264 actual scope definitions and 83 deletion specifications. It invokes the unchanged complete source collector, retains four-argument boundary verification, and checks every registered scope by default. Root module imports, declarations, attributes and tail code are fixed in addition to method bodies, including checks against an extra implementation or raw owner getter. The new module's separate contract is bound by its complete SHA-256.

## Validation boundary

The work performed was byte comparison, Python AST inspection, partial typed-call extraction over the fixed overlay, and construction checks with the original marker predicates for 42 affected rows. No QA method, unittest runner, complete repository source scan, formatter, Rust compiler, native test, H operation or source gate was run. Prepared function and literal fences must be rebound to actual final formatting before final qualification. No budget, ignore rule, verifier or authority field is relaxed. The pure ledger codec is not treated as an authority boundary solely because it is public.

## Durable bytes and original failures

MANIFEST.json, ENCODING_MANIFEST.json and GITHUB_FULL_READBACK_LEDGER.json identify exact objects and their actual readbacks. The 4.74 MB raw packet was created as fab488b846bb1b1ef7a42b9b30be5773054e1a6a. Its first direct GET returned `Transport closed`, retained in RAW_PACKET_CREATE_AND_FIRST_FETCH.original.json. Three separately created and fully read-back base64 parts reconstruct the exact complete gzip and raw packet; this does not claim a successful direct GET of the large raw blob. The patch and detailed protection report also have lossless, fully read-back parts.

The 1.807 MB CALLERS postimage has an independent successful full Git readback, but is not a large evidence-leaf entry. Its complete before and after bytes are also inside the packet. The original source size allowance only appends the exact CALLERS SHA-256. No new large-file exception is added for evidence. All evidence-leaf entries in PLACEMENT.json are below 500,000 bytes.

Two local packaging-script assumptions failed before a packet was produced: the required inventory key was first misspelled, then its declaration order was incorrectly assumed to match boundary order. Both original scripts and explicit errors are preserved. The final script uses the real required_boundary_ids key, exact original order preservation, unique full-set equality and the real protected-row delimiter. These were preparation failures, not QA or gate outcomes.

The fullreadback ledger and this README are immutable sidecars. Their own successful readbacks, followed by the placement's successful readback, are recorded separately to avoid a self-containing hash cycle. Only blobs have been created; no tree, commit, source ref, evidence ref or PR was changed.
