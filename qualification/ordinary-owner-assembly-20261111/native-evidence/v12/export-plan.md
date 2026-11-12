# V12 fixed original-record export — review request only

**Status: prepared, not dispatched.** No h call, PTY, native command, workflow, source mutation or ref update was initiated for this export. Root must review the fixed request, obtain its intended independent review, and decide whether to dispatch that exact object.

## Fixed request

- Request Git blob: **8ddc60db11826a1de79342c3caed547e7623f2e2**; 120975 bytes; SHA-256 **5b8d6ee48c3ab5eb28bf3efdd8602eff26a72c327f3395e8f94933a5296c51d1**.
- Configuration Git blob: **eac6f2aea94ad2e20a49f04c64e964c67f587338**; 107127 bytes; SHA-256 **cecada081aae80f6e33d56e9715132f661490f718a51b1df4050fb4ade05cab9**.
- Host: `ai395`; executable: `/usr/bin/python3`; working directory: `/home/qq/af52-learning-local-decision-20261111`.
- Stable, as-yet-uninvoked export key: `af52-ordinary-894138f-original-records-export-v12-20261112`.
- PTY dimensions: 24 rows, 200 columns. No environment, credential, proxy or permission override is supplied.
- argv is exactly `-B`, `-c`, the original wrapper, the original exporter, and five ordered JSON configuration chunks. Each chunk is at most 24,000 UTF-8 bytes; the largest argument is 24,000 bytes, below 128 KiB.
- Concatenating argv[4:] reproduces CONFIG.json exactly. argv[2] and argv[3] reproduce the pinned wrapper/exporter exactly. The nested native request is JSON evidence only, never executed by the exporter.

If dispatch acknowledgement is uncertain, reconcile this same key/request/session. Do not issue a new key, re-export, retry native work or overwrite an existing output directory.

## Unchanged programs

| Program | Git blob | Bytes | SHA-256 |
| --- | --- | ---: | --- |
| Exporter | 79494fe659157c453d4f0804cb01581eecce6052 | 4,370 | 2c0bd59e9d484c955831fa0ea61fd859c989c5747c68266f5fa7d978d7887815 |
| Wrapper | e6560092b622a84e24c20ca7fb8b2589b0233cc4 | 146 | 869e8b6921d4bddd27c611590f19697a2983cb03b53732a18b426f0fd32fb49d |

Both were obtained from their exact Git objects and checked byte-for-byte by Git ID and SHA-256. The wrapper only joins the configuration arguments before compiling/executing this original exporter. It does not evaluate request objects inside the JSON.

The V11 configuration e084ab56a4d111ecc4369b0b96f80c0aa800a5cc was used as a shape reference, not as evidence or qualification for V31.

## One terminal source, one archive

- Source: **894138ff2c34dc54b0f31d3883a840639d076ea5**.
- Tree: **3c7e0963f8c32701066071f354c626aa5283687d**.
- Anchor checkout: `/home/qq/af52-learning-local-decision-20261111/ordinary-894138f-seven-final-v5/source`.
- Original records: `/home/qq/af52-learning-local-decision-20261111/ordinary-894138f-seven-final-v5/records`.
- Required terminal file: `progress.json`, exactly **30,883 bytes**, Git **4756f19cf98b490b59cc4dc996d18726e560b02f**, SHA-256 **ccb3080fec4eff1660037060a0a8eecd85d9513efbc6a1e71cefbb355b2476ef**.
- Exporter asserts the original terminal status is **failed**, with exactly the source/tree above, and requires the entire progress-file SHA.
- New output only: `/home/qq/af52-learning-local-decision-20261111/ordinary-894138f-original-records-export-v12-20261112`. Its existence is not assumed or probed; the unchanged exporter refuses if it already exists.

The original final identity 4837204c0249b659e99780b4752cc896a921c8d5 records the exact clean source/tree. The exporter separately checks current anchor HEAD/tree/status before and after reading records. It does not reset a dirty source or alter any source files or references.

## Original failed result to retain

The source-specific result 351d2801b2b3655708209af2ba3303b4c88d1212 and original execution f537410cfbbe89816aef58e5372914a5719fbd10 agree:

- Seven-package maintenance, binary checks and four QA groups passed on this fixed source: **221 + 5 + 5 + 5 = 236** QA tests. Caller self-test passed.
- The original full caller command failed at `q24_task_original_ready_observe`: unresolved possible `OriginalCellQ24TaskLedgerProducerV1::observe_learning` receiver in `codex-rs/hepta-agentd/src/circuit_q24_successor_execution.rs`.
- Original command elapsed time is **1163.66759224399 seconds**, command/executor exit **1**, `timed_out=false`, `output_limit_exceeded=false`. The separate launcher elapsed time remains its original recorded value; the two are not substituted for each other.
- Raw failure is exactly **203 bytes**, Git **8f0c9b2d86c6e1abb74e416a7b3d237779852817**, SHA-256 **d6f0e425e083cec0836e26fc27a852c326a0c0a851e0d81792fd8396d4ed076e**.
- Same-source helper build/preverify, ordinary seven-package behavior tests, Root17 and post-test helper verification were **not reached**.
- All five original cleanup stages passed: retain-source-and-drift, original-tool-sources, final-physical-source, read-only-reference and external-tools.
- Ordinary complete chains, positive adoption and ordinary NoUpdateRollback remain **0 / 0 / 0**. Independent C and actual daemon+Root OS restart are not accepted.

The export must preserve this failure; an archive verification result is not a native or business PASS.

## Original requests and PTY evidence

The complete parsed native request **176ddf60ccf8e863e722f6339457665b25e71514** is carried only under `requests/`. Its original raw body is separately pinned: 56,726 bytes, SHA-256 **581cc76224cb43a2d98d5b8d40cd9953f3de0b69b9c84065711862ca5051e7d8**. The unchanged exporter serializes parsed request/observation objects using sorted, indented JSON; those members are not claimed byte-identical to their original raw JSON blobs. Complete argument values are retained.

Original PTY observation **c852a801ddf009d48c8f1e0deb728ffedc7644cd** identifies session `dpty-7e0cb3ee560f53ffa65290d93ec1d5341c0e304c118581cafe3fa07bc9e2c7e2` and terminal exit 1 with complete capture and no capture error.

The two original byte pages cover [0, 6421) and [6421, 6987). Their per-page SHA values, bytes_hex, text bytes, contiguous offsets and failed terminal state were checked locally in memory against byte container **6a3d46b118a3e1e836c3cd19029cab228a49c5b7**. The complete PTY is exactly **6,987 bytes**, SHA-256 **b964af9eab374b69161382f9ba25e985060518f362a3f224b98649df9deb8883**, expected raw Git ID **7f15c033e06598bb07ad506826f655c033383722**. Original CRLF is retained in the embedded text value. This does not claim that a separate raw PTY Git object was newly created.

The existing Root-authored result summary is explicitly labeled an observation. It does not replace original execution/source/tool/custody/cleanup records.

## Existing export contract, unchanged

When Root dispatches, the original exporter will:

1. Create only the new output directory and refuse replacement of an existing one.
2. Run only read-only Git identity/status commands against the anchor; no Cargo, just, tests, native rerun, push, commit, reset or credential operation.
3. Recursively read the one records directory. Each retained file must be regular with link count one and at most 32 MiB. Only `helpers/bin/` executables are excluded by the original policy; original custody manifests and native build logs remain included. No new exclusion is added.
4. Retain all existing source inventories, execution logs, tool/runtime/custody and cleanup records, plus the declared request/observation JSON data. Total payload is bounded by the original 128 MiB limit.
5. Recheck source identity, each original file's device/inode/size/mtime and its byte hash. A mismatch fails; it is not repaired.
6. Write the original `MANIFEST.json` and `original-records.tar.xz`; read the archive back in memory and compare every member's bytes to the collected payloads. No archive extraction is performed.
7. Write original 48,000-character base64 parts and `export.json` with archive size/SHA/Git/member metadata. A caught failure retains `failure.json`; it is not converted to success.

Archive size, digest, member count and remote export success are deliberately unset before actual execution. No h dispatch or remote parse has occurred in this preparation task.

## Root request revision

V1 request f1567d380f8ae7e0506885104288a2ec9d9ef14d was never dispatched. V2 changes only argv[0] from -u to -B to retain the previous exporter invocation's bytecode-suppression option. The configuration, five chunks, original scripts, host, cwd, new output and one unused idempotency key are unchanged. V1 plan f33d3f626495f332228dcd10328695b2a2f1b08b, preparation manifest 2c4bc8d91b98b8ff715f9aca4ae37de96d15adc5 and its undispatched review 61106ec795f220db18c10b08378ed9ee90f621cd remain historical preparation only.
