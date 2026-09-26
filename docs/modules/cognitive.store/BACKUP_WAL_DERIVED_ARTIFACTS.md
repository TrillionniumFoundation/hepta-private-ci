# Backup, WAL and derived-artifact handling

A cognitive backup is a database/WAL/journal generation plus owner identity, schema digest, exact current-cut anchor and active-pointer digest.  Copying only the main SQLite file is not a valid backup while WAL state is live.  Backups are encrypted, generation-labelled, immutable and excluded from ordinary retrieval.

Restore never opens the supplied source path as a writer.  The descriptor-bound recovery boundary copies it into a private generation, validates exact currentness and authority, checkpoints and publishes.  A backup older than the independently retained witness is rejected even when SQLite integrity succeeds.

Deletion disposition is tracked independently for: active database, WAL/SHM/journal, recovery candidates, offline backups, search indexes, KG projections, prompt/context caches, evaluation datasets and learned artifacts.  A logical tombstone closes retrieval immediately; physical media deletion and derived-artifact revocation require receipts from their owners.  Unknown acknowledgement remains pending or indeterminate, never “deleted”.
