# ACL lock preflight repair evidence

The original hosted ACL observe job stopped at the lock preflight; it did not
execute the Windows native tests. The Matrix source union added one existing
workspace dependency, codex-utils-path, to codex-hepta-matrix-sdk.

The repaired guard requires that addition exactly once, removes only that
addition from the comparison, and verifies the original complete dependency
fingerprint. The exact anyhow record, every source pin, native platform guard,
test list and budget remain unchanged. Nine executions of the actual extracted
inline policy cover the reviewed lock and eight rejected changes.

The archive retains the complete original failure, both lockfiles, both
workflows, extracted policy code, the review patch and original maintenance
receipts. Every member was recovered and compared by length and SHA256.
These checks qualify the preflight repair. They do not qualify Windows
isolation or replace its still-failing positive tests.
