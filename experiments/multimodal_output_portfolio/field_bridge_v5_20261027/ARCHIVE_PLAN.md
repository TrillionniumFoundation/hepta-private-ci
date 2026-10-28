# V5 raw evidence archive and persistence plan

Status: **PLAN ONLY; NO ARCHIVE BUILD, RESTORE OR UPLOAD ATTESTED**.
This post-design preservation plan changes no frozen execution, audit source,
scientific threshold or data access. It covers the one registered V5 development
study `hepta.field-bridge.v5.baseline-gate-transaction.20261027.1`, including
negative results and any failed/partial execution. It does not reopen V2/V3/V4.

## 1. Existing constraints and evidence

The following repository records were read at baseline
`0acfd9b27db910c180b0d8911f39aea469b7f864`:

- [Blob-size workflow](../../../.github/workflows/blob-size-policy.yml) passes
  `--max-bytes 512000` to [the checker](../../../scripts/check_blob_size.py).
  It covers changed binary and nonbinary blobs. The exact-path allowlist has
  no field-bridge raw evidence entries. A file equal to the limit passes;
  one larger than it fails. This is not a 50/100 MB policy.
- [V4 restore guide](../field_bridge_v4_20261027_review/ARCHIVE_RESTORE_GUIDE.md)
  requires terminal census, exact member hashes, deterministic packaging,
  full gzip/inner-gzip CRC and physical-EOF verification, literal restoration,
  archived-code reanalysis and separate postpackage receipts. It preserves
  partial failures and refuses insufficient disk space before writing.
- [V2 rejection record](../field_bridge_v2_20261027/evidence/PERSISTENCE_AUTHORIZATION_BLOCKER.json),
  [V3 concrete request](../field_bridge_v3_20261027/evidence/PERSISTENCE_REQUEST.json)
  and [V4 approval status](../field_bridge_v4_20261027_review/PERSISTENCE_APPROVAL_STATUS.json)
  record three automatic-review rejections before helper-process/upload start.
  The proposed destination was ChatGPT Library; the objects were private
  experimental/model archives and verification reports. The reviewer required
  end-user-authored approval naming the files and destination. Generic
  continuation, even after an assistant enumerated the files, was insufficient.
  GitHub code/result publication was recorded as a separate authorized activity.

These historical records establish a destination-specific unresolved approval
boundary, not a claim that V5 has already been rejected. They do not authorize
retrying old uploads or transferring equivalent raw bytes through another
destination. Splitting/encoding files or editing the CI allowlist is not an
authorization mechanism.

## 2. Expected inventory and size

The completed design has 72 paths, 432 macro decisions, 1,512 transactions
(216 guard-48 and 1,296 guard-8), and 3,240 expected trace records before any
exception. Use actual inventory and exact bytes at terminal completion.

| Payload | Expected count | Planning size | Basis |
| --- | ---: | ---: | --- |
| Terminal adapter + SGD checkpoints | 72 | 5.6–10.9 MiB | V3 verified checkpoint range 81,461–158,645 bytes |
| Complete recorded trace streams | 72 | 10–35 MiB budget | More guard-8 receipts; exact compression not known yet |
| Task/clean hard-output NPZ | 150 | About 174 MiB | 144 path outputs + 6 frozen originals; V3 same-panel byte counts |
| ENDPOINTS, phase/path seals, logs, audit and provenance | All | 5–20 MiB budget | Census after terminal execution |
| Restored original assets | 10 current files | 23.50 MiB | Local stat: 24,640,277 bytes including restoration receipt |
| Frozen source and old input dependency closure | All required | Several MiB | Banks/controllers alone total 1,203,220 bytes |

Plan roughly **230–280 MiB of payload**, with a 320 MiB provisional packaging
allowance; these are estimates, not verified bounds or a promise of compression.
The hard-output estimate uses the historical verified manifest:
`field_bridge_v3_20261027/evidence/ARCHIVE_INTEGRITY.json` records 96 task files
totalling 188,216,219 bytes, 96 clean files totalling 45,134,379 bytes, and six
original files totalling 7,320,438 bytes. Scaling the path outputs to 72 gives
182,333,386.5 bytes including originals. No new scientific output was opened
to make this estimate. Checkpoint metadata changes may slightly change sizes.

The 72 checkpoints preserve the recorded terminal adapter tensors and optimizer
state. Traces preserve the recorded decisions, state identities, guard evidence
and costs; they do not contain every intermediate tensor, gradient or RNG
snapshot. Archive documentation must not imply reconstruction of unrecorded
intermediate states or re-execution of model/observer calls.

## 3. Concrete local package

Prepare an external staging directory such as `v5_archive/`, separate from the
sealed run and Git source tree. Include:

1. `run/`: every terminal training/evaluation file, all 72 checkpoints and
   traces, 150 emitted-media files, endpoint arrays, START/COMPLETE/FAILED and
   PATH/PATH_FAILED records, execution logs and the independent audit result.
   On failure use an explicit partial-run disposition and the actual inventory;
   do not fabricate missing completion records or discard failed work.
2. `repository/`: the frozen V5 source/protocol/calibration and the exact V3/V4
   source and evidence dependencies needed by the frozen runner and auditor.
   Preserve relative paths so restored code resolves its original inputs.
   Include old source-role identities, banks, heads, ordinary selection,
   historical endpoint records and runtime/source identities used by the audit.
3. `registration/`: source freeze, pinned commit IDs, source hashes, runtime
   versions, terminal disposition and a one-to-one ledger-to-member mapping.
   Include every externally stored file required by a frozen read dependency.
4. `assets/`: the ten original restored asset files, exact restoration receipt
   and downloaded-source archive identity. Include their bytes once; omit the
   duplicate 62,166,608-byte downloaded tar when its exact restored members
   and provenance are retained. State this omission explicitly.

Reference historical V2/V3/V4 archives by verified identity instead of nesting
them. Do not imply those historical raw archives have been durably uploaded.
Exclude bytecode, caches, the regenerable virtual environment, the output
archive itself and postpackage receipts. Retain exact frozen runtime versions;
absence of bundled wheels means this is not a hermetic runtime distribution.

Before creation, enumerate each regular file with portable member path, source
path, role, byte length and SHA-256; require unique safe relative paths and no
symlinks, devices, traversal or undeclared aliases. Rehash against the frozen
inputs and sealed phase inventories. Write `ARCHIVE_INPUTS.json` and a canonical
`MANIFEST.json`; the latter is the first regular tar member and lists all other
members. Keep its SHA-256 in an external build receipt.

Use deterministic tar metadata and gzip (`mtime=0`, no original filename),
with exclusive output creation and preserved `.partial` on failure. Calculate
required disk from actual tar headers/padding, a valid matching-compressor
worst-case bound, chosen restore bytes, optional split/concatenation copies,
receipts and at least 32 MiB reserve. Refuse insufficiency without deleting
unique evidence. Do not assume the historical V4 scripts accept a V5 schema;
any packaging adaptation belongs outside the frozen scientific modules.

## 4. Optional volumes and integrity gates

Canonical file: `hepta_field_bridge_v5_20261027_evidence.tar.gz`.
If a subsequently authorized destination needs smaller transfers, split its
exact byte stream into ordered 32 MiB volumes named `.part000`, `.part001`, etc.
At the estimated size this is approximately 8–10 volumes. Last volume may be
shorter. Do not put these raw volumes into Git to evade its blob-size limit.

`ARCHIVE_PARTS.json` records the full archive SHA-256/bytes, manifest SHA-256,
volume size, total count and every volume's index, name, offset, bytes and
SHA-256. Verify each part, contiguous coverage with no gap/overlap, concatenated
length and whole-stream SHA. Part hashes alone do not establish archive health.

Then independently read the full gzip to physical EOF, verify outer CRC, tar
termination, exact member count/inventory and every member length/hash. Verify
inner gzip CRC/EOF and NPZ ZIP-member CRC; reject extra or unsafe members.
Restore into a fresh directory with no access to the original run tree. Verify
restored files against the manifest. Run the **restored frozen V5 auditor** on
the restored run and restored input freeze under the pinned runtime. It must
recheck all traces/checkpoints/media hashes and exactly reproduce the original
descriptive comparisons, resource accounting and development-entry result.
This is artifact analysis only, with no new model/observer execution or holdout.

Record build, full-stream verification and literal-reanalysis results outside
the tar, binding archive/manifest/source IDs and their own sizes/hashes. Avoid
self-referential manifests. A negative scientific result must reproduce as
negative. A partial failed run can have a valid preservation archive while
remaining an incomplete study; its audit failure is not relabeled PASS.

## 5. Authorization and durable-delivery decision

| Action | Present disposition |
| --- | --- |
| Read current records; prepare this plan | Authorized and performed |
| Finish fixed V5 execution; hash, package and restore locally | Within the authorized research/preservation work; no new outcome collection |
| New branch with source, summary and small manifest/verification receipts | Parent reports authorized; observe 512,000-byte CI limit and inspect exact diff |
| Upload V5 raw archive/volumes or private model/media assets | No upload authorized by this plan; verify actual user wording for named objects and destination |
| Retry historical V2/V3 Library upload or substitute another raw destination | Historical explicit-approval blocker persists; do not retry generically |
| Change allowlist, add LFS, publish Release/Actions artifacts or use another storage service for raw | Separate concrete destination/action decision; no bypass assumption |

The root agent has the full user conversation and must honor any already
explicit authorization. Do not ask again if it names the relevant objects and
destination. Otherwise finish the reviewable package first, then present its
exact filenames, sizes, hashes, contents and destination for the missing
approval. Explain the prior automatic-review rejection and its stated reason;
do not describe the obstruction as a scientific blocker or a failed experiment.

After an authorized upload, record remote object IDs, bytes, checksums and
retention/durability semantics, and download to verify exact archive/part hashes
when supported. A successful local restore or Git summary alone is not durable
raw persistence. If transfer remains blocked, report `LOCAL_VERIFIED` and
`PERSISTENCE_BLOCKED` separately and preserve the complete local artifacts.
