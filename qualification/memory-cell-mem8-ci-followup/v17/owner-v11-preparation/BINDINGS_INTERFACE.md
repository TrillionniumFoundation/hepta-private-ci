# Actual bindings interface

Do not render until the source and evidence publication receipts are real and fully read back. This document is a schema description, not a populated binding or a claimed publication.

Top-level keys required by `prepare_owner_v11.py`:

- `schema`: `mem8.owner-v11.actual-publication-bindings.v1`.
- `checkpoint_utc`: the explicit UTC observation time.
- `source`, `evidence`, `owner_previous`: publication objects described below.

Each publication object contains `head`, `tree`, `pr`, `draft: true`, `receipt`, `receipt_repository_path` and `receipt_selectors`. Source also contains the actual frozen `base`. The expected PR numbers are 5935, 5889 and 5897 respectively. The previous owner head is fixed by the full baseline; the current source/evidence heads are parameters.

`receipt_repository_path` is the planned location of the unchanged supporting receipt in the owner proposal. The ledger labels it `path_in_this_owner_proposal`; it does not pretend that a later publication receipt already lives in the earlier source/evidence commit. Root must attach those three exact supporting files when publishing the owner proposal. Their future owner commit identity is recorded separately after publication.

`receipt` has exactly `local_path`, `bytes`, `sha256`, `git_blob`. Relative local paths are resolved under `--root`. The publication object's `receipt_selectors` maps these seven names to actual JSON pointers in that frozen receipt:

| Name | Required actual value |
| --- | --- |
| `head` | This object's head |
| `tree` | This object's tree |
| `pr` | Its expected PR number |
| `draft` | Boolean true |
| `raw_ref_head` | This object's head from the actual ref readback |
| `body_equal` | Boolean true from the full submitted/readback body comparison |
| `update_success` | Boolean true from the actual expected-head update result |

Different original root receipts have different shapes. Selectors preserve those original bytes instead of normalizing or inventing an intermediate receipt. For example, the already published V10 owner receipt has `/after/head`, `/after/tree`, `/pr`, `/after/draft`, `/after/head`, `/full_PR_body_equal_to_submitted`, `/ref_update_result/success`. The actual source receipt uses its own recorded shape; do not assume that example applies to it.

The evidence object also contains `objects`, a map whose keys are exactly all IDs in the reviewed frozen selections file. Each value has the original report's `bytes`, `sha256`, `git_blob`, its actual repository `path`, and `root_full_readback_verified: true`. For a report retained as an archive member, additionally supply `archive_member`; `path` then names the published archive and the identity binds the full extracted report. This mapping is only populated after the root has performed that actual readback.

Run the local generator with the reviewed files' actual SHA-256 values:

```text
python prepare_owner_v11.py
  --baseline /absolute/path/to/mem8-owner-v10-root/BLOCKERS_FINAL.json
  --root /absolute/path/to/workspace
  --facts /absolute/path/to/reviewed_frozen_report_selections.json
  --facts-sha256 ACTUAL_REVIEWED_FACTS_SHA256
  --bindings /absolute/path/to/actual_publication_bindings.json
  --bindings-sha256 ACTUAL_REVIEWED_BINDINGS_SHA256
  --output-dir /absolute/path/to/new_local_proposal_directory
```

The displayed argument tokens are instructions, not usable fake pins. The program rejects missing or mismatched values. It writes only `BLOCKERS_PROPOSED.json` and `LOCAL_INVARIANT_AUDIT.json` in a previously nonexistent directory. It never invokes Git or a remote API.
