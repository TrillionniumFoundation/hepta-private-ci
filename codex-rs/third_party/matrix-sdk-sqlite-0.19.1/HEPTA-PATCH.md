undefined

## Cipher scheduling composition (qualification pending)

Port scheduling and checked KDF optimization from PR #6358 exact source `842a49e96d7e6960267913825e01d53d96aab971` onto SQLite proposal `af59210d1e66268bd45cd5643b96bfa5610e39e4`. Preserve rusqlite 0.43.0 / libsqlite3-sys 0.40.0 and the original provenance above. Added cipher_task.rs/store_cipher.rs and modified utils.rs/lib.rs/error.rs retain #6358 source; manifests only add Tokio rt. Preserve licenses, five-second production startup deadline, original KDF, and error propagation. No database handle enters the blocking closure; only the awaiting caller writes its returned export. Old qualification does not cover this combination or current store_version_migration. Generate current graph locks rather than importing old locks.

Follow-up qualification correction: apply current repository rustfmt's item-per-import layout to cipher_task.rs (no semantic change); replace the inherited unversioned Cargo KDF override with the new exact-version checked override rather than retaining overlapping selectors. The old #6358 storage_upgrade target is absent from this baseline and is not counted as executed; current store_version_migration and existing owner/durable/cancellation targets remain mandatory.
