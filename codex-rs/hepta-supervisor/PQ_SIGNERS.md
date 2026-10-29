# Explicit PQ issuance for original FinalUse tools

The existing grant, operator-approval, and revocation-feed executables accept
`--pq-key-id HEX` as their final option. This selects the canonical ML-DSA-65
profile and requires a separately pinned 32-byte public-key identifier. Without
this option the existing classical profile remains explicit. A PQ consumer must
select the PQ profile in its own configuration; merely installing these tools
does not activate a host-wide migration.

## Wire and ownership

| Executable | Input | PQ output | Classical output |
| --- | --- | --- | --- |
| `hepta-final-use-signer` | Exact grant JSON, maximum 16 KiB | Grant schema 2, 3,309-byte signature | Grant schema 1, 64-byte signature |
| `hepta-final-use-approver` | Exact grant JSON, maximum 16 KiB | Approval schema 2 bound to the grant signing digest | Approval schema 1 |
| `hepta-final-use-revocation-signer` | Revocation head JSON, maximum 8 MiB | Feed schema 3, at most 256 revoked grant IDs | Feed schema 2 with the existing capacity |

Grant schema and the CLI-selected profile must agree before the seed is opened.
There is no automatic schema rewrite or alternative-verifier fallback. Each
role uses its own domain-separated message. PQ signatures use the canonical
`codex-hepta-contracts::pq_auth` implementation, pure ML-DSA-65 with an empty
FIPS 204 context; application domains are inside the exact signed message.

The PQ key identifier is
`SHA-256("TRNM/PoN/PQKey/v1\0" || strict_ML_DSA_65_SPKI)`. The signer derives
the public key from its owned seed and requires an exact match to the supplied
identifier. The identifier must come from the operator's approved trust policy.
Computing it from an untrusted request would remove that independent check.

On Unix, the seed must be exactly 32 raw bytes in an owner-only regular file,
owned by the effective user and with one hard link. The final pathname component
is opened with `O_NOFOLLOW | O_NONBLOCK`; metadata is checked on the opened
descriptor. Reads are limited to 33 bytes and seed buffers are zeroized. This
does not establish protection of ancestor directories, hardware custody, or
operator separation. Other platforms fail until an approved custody backend is
provided.

The approval tool signs the reviewed grant proposal; it does not independently
fetch or verify an issuer signature. The revocation tool signs a proposed head;
it does not establish the previous durable head. Original consumer owners must
still verify role keys, exact bindings, validity windows, current revocations,
durable monotonicity, and nonce use. The inference worker and Bao have different
existing approval requirements; using these three tools does not add an
operator approval to a consumer that does not require one.

## Commands

Run from `codex-rs` after building the three executables with the
`production-authority` feature. The grant JSON must already use schema 2.
Examples use distinct externally supplied role pins and owner-only seed files:

```sh
hepta-final-use-signer sign --key issuer.seed \
  --pq-key-id "$ISSUER_PQ_KEY_ID" < grant.json
hepta-final-use-approver approve --approver-id operator --key operator.seed \
  --pq-key-id "$OPERATOR_PQ_KEY_ID" < grant.json
hepta-final-use-revocation-signer sign --distributor-id distributor \
  --key distributor.seed --issued-at-unix-ms 1000 --expires-at-unix-ms 20000 \
  --pq-key-id "$DISTRIBUTOR_PQ_KEY_ID" < revocation-head.json
```

The example timestamps are fixture values, not a production clock policy.
Failures write diagnostics to stderr and produce no signed JSON on stdout.

## Repeatable executable verification

`tests/pq_cli_smoke.py` invokes the actual three executables with disposable
fixed test seeds. It requires Python with `cryptography` exposing ML-DSA-65 and
an OpenSSL backend that supports it. The script also requires a separately
built `hepta-contracts` `pq_message_oracle` example. It does not download or
install dependencies or silently skip missing capabilities.

```sh
cargo build --locked --release -p codex-hepta-supervisor \
  --features production-authority \
  --bin hepta-final-use-signer --bin hepta-final-use-approver \
  --bin hepta-final-use-revocation-signer
cargo build --locked --release -p codex-hepta-contracts \
  --example pq_message_oracle
python3 hepta-supervisor/tests/pq_cli_smoke.py \
  --binary-directory target/release \
  --canonical-oracle target/release/examples/pq_message_oracle \
  --report /tmp/hepta-pq-cli-report.json
```

Adjust the binary paths when using `CARGO_TARGET_DIR`. The JSON report records
the exact binaries, source files, harness, oracle, independent backend, and
individual outcomes. The 34 cases cover all three PQ roles, the 256-entry feed,
independent OpenSSL verification and canonical verification, classical
compatibility, wrong domains, profile/schema mismatches, wrong pins, unknown
fields/options, input limits, and unsafe seed-file shapes. These are issuance
and refusal tests, not proof of deployment custody, application consumption,
whole-Hepta PQ activation, or PoN quantum-work security.
