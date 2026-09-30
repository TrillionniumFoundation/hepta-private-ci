# Target storage acceptance contract

A production SQLite owner is qualified only by an external receipt using
`hepta.secrets-target-storage-acceptance.v1` and bound to the exact source head
and source tree. The verifier rejects CI-local volumes and unsafe/non-local
locking filesystem profiles.

Required target tests are WAL, fsync, byte-range locking, disk-full, inode-full,
power-loss, snapshot/restore, container restart, node migration and corruption
detection. Every test carries a content digest for its immutable evidence.

Four distinct principals must attest the secrets/security, SQLite/storage,
product-caller and operations/SRE roles. The receipt must be signed and record
operator acceptance. Source CI runs without such a receipt and therefore emit
`targetStorageProfileQualified=false`; promotion/release uses
`--require-qualified` and fails closed.
