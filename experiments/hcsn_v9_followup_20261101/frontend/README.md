# Frontend prerequisites and recovery facts

This continuation reuses `hcsn_v7_support_20261101/restore_check.py`; it does not rebuild the missing v6 model. `CURRENT_ASSET_STATUS.json` is the actual local check, which exits **2 / HOLD**. Both original commit objects and the pinned v6 protocol are absent, all 27 protocol fields remain unavailable, and no strong-audio or complete historical recording ledger was recovered. `RECOVERY_SEARCH.json` separates this request's REST observations from the parent agent's Library search observations. The expected package hashes come from the pinned prior report; their actual bytes were not obtained or verified.

The additional checker catches the gap not covered by the baseline verifier: source-recording reuse through a new prefix, crop, pair or filename; inconsistent actor IDs; exact-media aliases under another recording ID; and strong-audio bytes that differ from the frozen protocol. Canonical CREMA-D IDs use uppercase stems such as `1001_DFA_ANG_XX`, without extensions or crop suffixes. Actor reuse is reported separately; a new recording by a historical actor is never labeled a new actor.

```bash
python -m experiments.hcsn_v9_followup_20261101.frontend.check_assets \
  --repo "$PWD" --out /new/output/FRONTEND_ASSETS.json
```

Without recovered assets this must exit 2. The optional `--handoff` names a repository-relative JSON file of schema `hcsn-v9-frontend-handoff.v1`, with `assets` entries for `strong_audio`, `common_content_head`, `projection_alignment`, and `encoder`. Each entry contains a relative `path` and `sha256`; the digest must equal the corresponding field of the completed, frozen v7 protocol supplied with `--protocol`.

The protocol's exclusion manifest must contain `historical_owner_ledgers` entries (`version`, `path`, `sha256`) covering v5 and v6, and the union `recordings`. Every ledger must already be byte-bound in the original pinned v6 protocol's `inputs`; a newly asserted complete list cannot qualify. The supported explicit ledger format is `hcsn-recording-owner-ledger.v1`, containing `version` and `recordings`. Unknown recovered layouts fail closed and require a reviewed parser, rather than extracting guessed IDs from filenames. Each recording has `recording_id`, matching `actor_id`, and `media_sha256`. Development/confirmation manifests contain `recordings`; confirmation additionally binds actual `media_path` bytes. All paths are confined to the repository, and confirmation IDs/actors must match the frozen protocol.

These checks verify byte consistency and declared inventory nonoverlap. Historical owner-ledger exhaustiveness and authenticity, empirical frontend quality, independent calibration, live execution and the scientific D−B/economic gates require separate evidence. A successful prerequisites check alone never sets quality or production acceptance true. No admitted handoff was created in this continuation.

Seven substantive controls passed: historical/development overlap, raw-media aliasing, noncanonical IDs/actor mismatch, missing inventories/digests, wrong strong-audio bytes/path escape, missing baseline refusal, and separate reporting of reused actors. Their fixture recording rows and bytes are explicitly synthetic and provide no real AV quality evidence. Exact command, source hashes and output are retained in `VALIDATION.json` and `VALIDATION.log`; repository formatting is coordinated by the parent agent after all parallel edits.
