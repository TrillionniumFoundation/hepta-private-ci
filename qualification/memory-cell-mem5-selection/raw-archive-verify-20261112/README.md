# MEM5 raw archive: independent read-only strict-v2 content qualification (2026-11-12 UTC)

## Exact inherited identity and non-repetition

Evidence-only descendant of #5684 at `865aa66a98bf4a78229650ebd0489ba527e91126` (stacked on #5680). Original frozen actor source remains `5fa0d0e462cd1393f4f9e95565ff5993e9bad29a` / tree `7b3431e21f604ea5381592c2509db4f26ea91f7d`; original MEM5 actor job `1a1c46734c8-cf39-2eb` and 108 completed episodes/54 paired cases were **not** restarted, reselected, or rescored. Original archive idempotency key `mem5-raw-archive-5fa0d0e-20261110-v1` is unchanged; original start and reconcile remain unknown at the durable-job-identity layer.

## New original, read-only observation

At `2026-11-12T00:46:44.153Z`, ai395 launched **only a read-only verifier**, *not an archive creation or any actor process*:

```sh
/usr/bin/python3 -B /home/qq/mem5-selection-20261110-4b3362/archive-run-strict-v2-6f57a286.py \
  --output /home/qq/mem5-selection-20261110-4b3362/raw-archive-5fa0d0e-v1 \
  --verify
```

- Verifier SHA-256 independently reported by `file_info`: `3e8466d63a03306f8e52de6e5f68bd378ce235731f98f9022ec47a4696677897` (16,669 bytes, exact published 469-line strict-v2).
- Existing output `INDEX.json` found at the **original output path**, 2,764 bytes, SHA-256 `470cb2217d2d4727c551b6f935f8f1ffaa66f7702af87ea1fdaa15b86e0b69f4`. It self-reports `all_regular_files_included=true` and `source_owner_authenticated=false`; these two fields are *producer claims*, not independently established owner attestation.
- Read-only verifier durable job `1a1cd38a5b9-2564-1227`; separate key `mem5-raw-strict-v2-verify-readonly-20261112-v1`, for verifier identity only. `process_wait` reported `succeeded`, `exit_code=0`, `terminal_publication_confirmed=true`, `output_complete=true`, `output_durable=true`, stdout 301 bytes / stderr 0 bytes, neither log truncated, no automatic retry.
- The complete original stdout (newline-terminated) was:

```json
{"all_logical_files_reconstructible": true, "assets": 84, "logical_bytes": 77913835, "logical_files": 4000, "manifest_sha256": "c98d559d76dee6d80b509397813e5f57128e53174d2e05b527f1df13a2339304", "source_owner_authenticated": false, "status": "verified", "unique_chunks": 2859, "unique_objects": 2825}
```

Verifier read all 84 assets (1 manifest tar.xz plus 83 object tar.xz), checked full asset identities/hashes, decompressed and checked bounded canonical tar members/trailers, reconstructed all unique objects from their chunks, matched exact file/object mappings and directory asset roster. Its reported complete content scope is **4,000 logical regular files / 77,913,835 logical bytes / 2,825 unique objects / 2,859 unique chunks**. This establishes independently executed *logical archive content reconstruction under the pinned verifier*, a new subgate compared with the prior `INDEX` and source-job UNKNOWN.

## What remains deliberately OPEN

1. The **original archival start job ID**, retained process status/logs and historical idempotency outcome remain `UNRESOLVED / UNKNOWN`. The local output existence and read-only verifier success do not identify which original job produced it. A current `process_list_page` snapshot returned a pending cursor; continuing it was explicitly rejected as invalidated. No alternate key or archive start was attempted.
2. Verifier ran on the *same ai395 storage*; no second-host independent restore, independently authenticated owner-source identity, cold recovery or remote asset preservation is claimed. The 84 archive assets remain on ai395, **not uploaded as a full raw corpus to GitHub**.
3. Source snapshot claims, complete sidecar/pixel re-execution, native owner/authentication, positive/NoUpdate selection, sealed outcome, matching full costs and neural-specific benefit are not qualified by this verification.
4. Existing MEM5 `20/54` rule vs `11/54` neural, 9 wins/45 ties/0 losses remain **released development validation**, not sealed confirmation or scientific proof.
5. Required repository CI and cross-version revocation/dependency/expiry remain separate. All adoption gates stay **Draft / HOLD / NoUpdate**, with no merge or production adoption.

The archived original data, failed/UNKNOWN records, original archive key, original Actor job and security gates must remain unchanged. This report is an evidence-only audit of a new *read-only* qualification, not a rewritten historical status.
