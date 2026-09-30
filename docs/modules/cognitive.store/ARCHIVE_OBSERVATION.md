# Archive publication observation without replay

This extends `ARCHIVE_RUNBOOK.md`, `RETRY_RECONCILE_MATRIX.md` and the existing
trusted-host archive command. It does not add a fact owner, archive writer,
production execution path, source mutation, erasure provider or activation grant.

## Purpose and ownership

The existing archive and restore commands preserve a possibly published output
when a final directory sync or acknowledgement is uncertain. Repeating either
command against an existing destination is deliberately rejected. The observation
mode now inspects that exact operation's output through the same bounded decoder
and native `cognitive-store-archive-check` owner oracle, using private scratch.
It never republishes the output or interprets its absence as proof of NotApplied.

`archive.py --reconcile-plan` is the ordinary command entry. Its helper
`archive_observation.py` contains read-only reconciliation, not another storage
backend. The normal restore path also uses the shared `decode_archive_image`;
no fixture-only decoder can make production archives appear valid.

## Fresh observation authority

The original archive/restore plan, its independent expected payload digest, the
current owner-trust digest, encryption key and approved native-verifier digest
remain mandatory. The original operation may have expired, but only when a
separate, presently valid signed observation plan names its exact payload digest.
An expired execution grant never permits a new archive, restore or replacement.

The new observation payload has exactly these fields:

```json
{
  "schema": "hepta.cognitive.archive-observation-plan.v1",
  "request_id": "reconcile-archive-001",
  "operation_plan_sha256": "<independently retained original payload digest>",
  "purpose": "reconcile_publication",
  "created_at": 1,
  "expires_at": 2,
  "scratch_parent": "/trusted/private-observation-scratch"
}
```

The times above are structural examples, not usable authority. Request ids and
integers use the existing bounded lifecycle validators. The scratch directory
must already exist, be canonical, owned by the process uid and inaccessible to
other users. It must not overlap either operation path or the live fleet in
either direction. Cold-image scratch is bounded by the existing 128 MiB profile;
plaintext scratch is not a backup and its unlink is not a physical-erasure proof.

Use the existing Ed25519 envelope with exactly `payload`, `signer_id`, `key_epoch`
and `signature_hex`. Signing bytes are the existing lifecycle domain
`hepta.cognitive.lifecycle-observation.v1` plus NUL, followed by canonical sorted-key
ASCII JSON of `payload`, `signer_id` and `key_epoch`, with compact separators.
Duplicate keys, floating-point values and unknown critical fields are rejected.
The coordinator signs outside this repository; the command receives no private key.
Both expected digests must come from the trusted operation context, not be copied
from the untrusted inputs as a substitute for authentication.

## Command

```sh
python3 tools/cognitive-store-host-bootstrap/archive.py \
  --plan /trusted/original-operation.json \
  --expected-plan-sha256 "$ORIGINAL_OPERATION_DIGEST" \
  --trusted-owners /trusted/current-owner-trust.json \
  --expected-trust-sha256 "$CURRENT_TRUST_DIGEST" \
  --key-file /trusted/archive-key \
  --owner-verifier /trusted/bin/cognitive-store-archive-check \
  --reconcile-plan /trusted/current-observation.json \
  --expected-reconcile-plan-sha256 "$OBSERVATION_DIGEST"
```

Original and observation signatures, current trust, purpose, path scope and exact
operation identity are checked before inspection and again before reporting.
The final observation-time check rejects expiry during long native verification.
The original plan's current signer must still be trusted: revocation is not waived
to inspect a historical output. A retired key requires a separately governed trust
or forensic procedure, not a bypass of signature validation.

## Observations and error handling

| Result | Meaning | Exit |
|---|---|---:|
| `valid_archive_observed` | Exact archive plan, framed encrypted inventory, plaintext digest and native owner cut agree | 0 |
| `valid_restore_observed` | Exact cold output bytes and native owner cut agree; no SQLite sidecars | 0 |
| `missing_or_incomplete` | Destination or archive manifest was absent at preflight; publication remains unresolved | 3 |
| `owner_cut_rejected` | The approved native owner executed and explicitly denied the requested cut | 2 |
| Other validation, crypto, path or execution error | No accepted observation; preserve original evidence and investigate | nonzero |

Missing verifier binaries, failed subprocesses, bad signatures, missing segments,
mid-read disappearance and invalid owner reports are not converted into a benign
missing-output result. The native typed denial remains distinct even when the
archive command is launched as a script.

The versioned report binds both plan digests, owner, writer generation, exact cut,
image digest, observed artifact digest and time. `report_sha256` is an integrity
checksum, not a signature. Every report keeps `replay_authorized`,
`publication_durability_proved`, `grants_authority`, `production_activated`,
`hot_history_pruned`, `physical_erasure_proved` and `target_host_qualified` false.
A currently readable output proves neither a previous fsync nor a lost successful
acknowledgement. Retirement and writable recovery still require their separate,
current external evidence and authority.

No source or destination checkpoint, permission change, rename, sync, replacement
or deletion occurs in observation mode. Only a disposable private scratch file is
created and removed. Repeated observation is permitted; replay is not inferred.

## Signed-file admission

The shared `lifecycle.load_bounded` now requires POSIX no-follow, nonblocking and
close-on-exec descriptors. A FIFO cannot block before `fstat` rejects it. Regular
single-link inputs are limited to 256 KiB and must not be group/world writable.
Descriptor and current-path device, inode, mode, link count, size, mtime and ctime
must agree after the read. A valid old signature on an already opened descriptor
does not conceal replacement of the current trust pathname. This is not protection
against a malicious trusted process with equivalent filesystem privileges.

## Tests and acceptance boundary

The new `test_publication_observation.py` provides 35 regressions. Combined local
execution of it, the 45 existing archive tests and the 32 lifecycle tests passed
112 tests. They exercise real Ed25519/OpenSSL, HKDF/AES-GCM and filesystem behavior;
most archive protocol tests explicitly substitute native owner verification.
The existing `owner_integration` driver is extended to observe both the actual
archive and restored image, reject a signed stale cut through the real native
checker, and verify that observation does not change original bytes. It is called
by the existing Rust `cognitive_archive_owner` integration test, not a parallel
product implementation. No local Cargo/rustc/rustfmt was available, so this native
integration, full Rust compilation/lint, release recovery measurements and the final
source-head/base-merge workflow are not claimed as locally passed.

`QUALIFICATION_PLAN.json` retains all 36 predecessor commands and adds the independent
35-test observation command. `CURRENT_STATE.json` adds CS-ARCH-002 and CS-FILE-001;
its generated status/dossier and exact implementation map must bind this source.
All execution, host, acceptance, activation and release flags remain unchanged.

Destructive ancestry-safe hot pruning still requires checkpoint-aware schema and
recovery semantics from ADR-0001. The archive/observation pair does not implement
that pruning. Actual backup deletion, derived-artifact erasure, parameter unlearning,
independent witness governance and selected-host operational qualification remain
separate unproved work; no user data is erased by this change.
