# HA and storage boundary

## Local source implementation

The SecretLease registry is an owner-private SQLite database configured for
DELETE journaling and FULL synchronous durability. Final-use replay state uses
an owner-private, single-active authority directory with an atomic head snapshot
and append-only fsynced claim journal.

The final-use directory intentionally uses an OS exclusive owner lock. It is not
safe to turn this into active-active by placing the same files on an arbitrary
shared filesystem.

## Source limits

- final-use claims: 1,000,000 unique nonces per authority epoch
- revoked final-use grant IDs: 16,384 per revocation head
- dynamic secret response: bounded by the adapter's 1 MiB response limit

Operational thresholds, compaction/epoch rotation and disk-alert policy remain
deployment responsibilities.

## Active-active contract

A future distributed backend must atomically preserve:

1. check-and-insert nonce by authority epoch
2. monotonic compare-and-advance revocation head
3. create one lease operation fence exactly once
4. persist provider lease identity/lifecycle monotonically
5. survive failover without forgetting acknowledged operations or claims

Until such a backend is qualified, use single-active/fenced failover or shard
ownership so each authority/lease key has one active writer.
