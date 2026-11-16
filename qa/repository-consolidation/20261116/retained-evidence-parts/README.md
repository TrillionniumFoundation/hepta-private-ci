# Retained evidence parts

Six original evidence files exceed the repository's unchanged 512000-byte limit. Each is retained through two ordered parts of at most 500000 bytes, with its original repository path, Git blob identity, byte size, SHA256 and incoming commit identities in MANIFEST.json. The original whole blobs remain in the original incoming Git history.

The parts sit beside the former whole-file paths. Each adjacent *.parts.json index carries the complete ordered part roster and the reconstruction command. Three links in two evidence READMEs now point to those indexes. Exact original README bytes are retained under original-controls; the verifier permits only the three recorded link substitutions. Historical JSON manifests, failure records, file sizes, hashes and qualification status remain unchanged.

The archived JavaScript transport helper is presented in Prettier 3.5.3 format at its maintained path. Its exact original 4300 bytes are also retained under original-controls. The codec-format-equivalence.json receipt binds both byte identities and the identical Babel syntax tree after omitting source positions, lexical formatting tokens and raw-literal presentation metadata. Neither version was executed.

## Verify and restore

Run the byte verification and its corruption checks from the repository root:

~~~sh
python3 -B qa/repository-consolidation/20261116/retained-evidence-parts/verify.py
python3 -B qa/repository-consolidation/20261116/retained-evidence-parts/test_verify.py
~~~

To restore all six whole files and the three original controls at their original relative paths, name a new directory outside the repository:

~~~sh
python3 -B qa/repository-consolidation/20261116/retained-evidence-parts/verify.py --restore-to /tmp/hepta-retained-evidence-originals
~~~

Restoration refuses an existing destination and keeps the original large files outside the working tree. It writes raw files only; it does not unpack or execute archived content. The normal blob-size, spelling and formatting policies keep their existing limits and scopes.

A successful reconstruction establishes byte custody. It does not change any retained failure, incomplete qualification, scientific status or runtime acceptance result.
