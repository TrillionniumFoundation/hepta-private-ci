# Starlark dependency compatibility patch

This is the official crates.io `starlark 0.14.2` package, unchanged except
for its BLAKE3 dependency requirement: `=1.8.2` becomes `^1.8.7`.
Its original archive SHA-256 is `9062e866918dc4c9701c98ac99f7f4fa9e4b3b4edce306e147393bc75458c4fc`.

Matrix store encryption 0.19.1 requires BLAKE3 1.8.7. The older exact
Starlark constraint prevents Cargo from selecting that compatible version.
The official Starlark main branch already accepts the BLAKE3 1.8 family;
this patch retains the released 0.14.2 evaluator and all policy semantics.
No hashing preimage, builtin, language rule or executable policy changes.

Remove this patch after an upstream release admits the compatible BLAKE3
version needed by the workspace.
