# Full commit ancestry audit: reproducible evidence

This export preserves the 2026-11-20 native audit of TrillionniumFoundation/hepta-private-ci.
The original result is full-history-result.json. It captured 7,654 refs and a complete
78,730-commit parent graph, classified 483 protected names with 504 retained pins,
and compared the captured refs with the remote again after classification.

Run the standard-library-only offline integrity check from this directory:

    python3 verify_export.py

The check performs no Git command, network call, classification, merge, or deletion.
It verifies all exported-file SHA256 and Git blob SHA1 values, independently decompresses
every gzip part, checks contiguous byte and line offsets, and reconstructs exact original
coverage maps. A passing result confirms byte preservation of the recorded evidence;
it does not constitute a fresh remote audit, a build result, or permission to retire refs.

## Exact raw inputs

export-manifest.json identifies each raw artifact and its ordered gzip parts.
Each part is a standalone gzip stream, at most 262,144 compressed bytes, with
compression level 9, timestamp zero, no original filename, and line-boundary splits.
Concatenate each artifact's independently decompressed parts in manifest order to recover
the exact original bytes. The original whole-file byte size and SHA256 are in the manifest.

The captured, prefetch and fresh-ref JSON files were byte-identical and share one payload.
The live-integration target was identical to integration_0cee and is an explicit alias.

## Coverage maps without repeated name/SHA strings

coverage-summary.json records counts and original map hashes for covered, pending and
frontier names. The coverage-membership artifact stores each distinct map as indices into
sorted(captured-refs.keys()). Rebuild a dictionary using those names and captured SHAs,
then serialize with json.dumps(value, indent=2, sort_keys=True) plus one newline.
The verifier proves this reproduces all 12 original map files byte-for-byte through
8 unique map payloads. Repeated frontier and live-integration maps are explicit aliases.

## Native provenance

native/full-history-audit.py is the exact script executed on ROG.
native/full-history-process-request.json records its exact runtime request.
native/hepta_branch_consolidation.py and the input-protection-manifest artifact preserve
the exact reviewed implementation and policy used by that job. They are archived inputs;
the export and offline verifier do not execute them. The native script records absolute
paths and is not intended to be executed unchanged in this publication directory.

The successful preflight result, Git help, submitted preflight request, native launch
receipt and terminal status are retained under native/. The previous preflight's false
negative and preserved unknown-outcome record are identified in runtime-provenance.json.

prepare-export.py records the packaging algorithm. It only reads existing evidence,
requires a new output namespace, and writes export files. It never invokes Git or reruns
classification. Gzip generation is byte-deterministic with the recorded Python/zlib
versions and normalized headers. No native Git pack files are included.
