# Final independent E3 material preparation status

The original single material download failed at its fixed deadline. **SmolLM2 is not an available second teacher.** No recovery has run, no model was loaded, and no forward pass, generation, training update, or native task was added. The earlier README and status snapshot remain unchanged as time-stamped history; this final addendum supersedes their running status.

## Original identity and terminal evidence

- Model: `HuggingFaceTB/SmolLM2-1.7B-Instruct`.
- Immutable revision: `31b70e2e869a7173562077fd711b654946d38674`.
- Frozen manifest SHA256: `b26b537a35456f9ca92e4e28063ff14abf3679dfc38a20566c7ea32bd678a0b1`.
- Single owner: `dpty-bc061e21ff77217cf1d3fb17d2b21ac81035493f1411544cd887dd528ef240b3`.
- Observed terminal: exited, code 1, output complete, `TimeoutError: single download owner deadline reached`.
- Download wall time: 895.0006092050462 seconds. Downloader self CPU: 4.645742721 seconds. Whole-system cost, network headers and TLS overhead were not measured.
- Original result: [raw/DOWNLOAD_RESULT.json](raw/DOWNLOAD_RESULT.json), SHA256 `17a4ad6bf10b5f46c68a13ee22b93533b0f424c43803e011a909bbfe16d3f57c`.
- Exact terminal receipt: [final/OWNER_TERMINAL_RECEIPT.json](final/OWNER_TERMINAL_RECEIPT.json).

The nine support files completed and each retained file passed an independent disk hash check. The complete weight file did not exist. Observed new HTTP body bytes were 259,228,704; prior public metadata accounted for a further 63,447 bytes. These counts do not claim to include bytes inside an interrupted read that never returned to the application.

## Partial bytes retained

The original partial remains on desktop at:

`/home/qian-qi/work/hepta-e3-smollm2-materials-20261120-e9e051/materials/model.safetensors.partial`

Its length is 255,852,544 bytes. SHA256 is `8e6735418da3f4bd07d84db98f2fe73a1e5cdc34f69eef214f2e94db7926476e`; immutable read version is `2050:986438:255852544:1795151779951107064:1795151779951107064`. See [final/PARTIAL_FILE_IDENTITY.json](final/PARTIAL_FILE_IDENTITY.json). The incomplete binary is retained on the original host and is not placed in Git.

The frozen complete file requires 3,422,777,952 bytes and SHA256 `f55217be716b6a997b97b9d8d7eb6fad02e00858f5010ec24f64603c3a98a0e8`. The partial's own checksum establishes its retained identity; it does not establish the checksum of the missing complete model.

## Recovery plan frozen; execution not authorized or started

The corrected [final/range-recovery-plan-2/PLAN.json](final/range-recovery-plan-2/PLAN.json), SHA256 `db664b8449cee85fd414982adcfb8b4c435ee348997d02cc4d998e550ab5d979`, is a plan only. It has `recovery_authorized_to_execute: false` and `range_support_verified: false`. No Range request, support probe, second download owner, retry, or resume has run.

The plan preserves the original partial and freezes 95 contiguous, non-overlapping ranges over the remaining 3,166,925,408 bytes, with at most four network workers. Each segment may be attempted once. HTTP 206, the exact Content-Range and total length, identity encoding, exact body length, and per-segment stream and local-extent hashes are required. HTTP 200 or a mismatched response is rejected. Only a complete independent disk SHA256 equal to the original frozen LFS digest would allow a future model file to be declared ready.

A future implementation must itself be retained and admitted before any newly authorized owner. The proposed single owner retains a 895-second alarm within the 900-second wall cap. Direct writes into disjoint extents avoid storing duplicate segment binaries; the old prefix is copied read-only and left intact. Conservative cumulative acquisition HTTP body bound is 3,427,266,135 bytes, including prior metadata, observed original transfer and a 1 MiB reserve for the interrupted read. Peak retained material storage bound is 3,690,422,458 bytes. Both are below the unchanged 4 GiB cap.

The measured original weight transfer retained about 313,184 bytes per second. Completing the remainder in 895 seconds would require about 3,538,464 bytes per second before setup. Four times the measured rate is still below that requirement. Parallel speedup has not been measured, and this plan does not promise completion within the deadline.

### Plan-generation correction preserved

The first unexecuted plan contained a manual transcription error in the expected full weight SHA. Its original bytes are retained at [final/range-recovery-plan-1/PLAN.json](final/range-recovery-plan-1/PLAN.json), SHA256 `ed66767d384cea56281ef06d1799d093b30eaa7feb45caa4290b0afb17901a81`. It must not be used for execution.

The corrected second plan reads the expected LFS SHA directly from the admitted original frozen manifest, checks its format, binds the invalid predecessor and records why it was superseded. Both metadata-only owners exited 0 and made zero network downloads and zero model calls. Their exact scripts and receipts are retained in [final/PLAN_CONTROLLER_RECEIPTS.json](final/PLAN_CONTROLLER_RECEIPTS.json). Neither plan is an implemented or executed downloader.

## Experiment accounting and limits

This preparation adds zero model loads, zero forward passes, zero generations, zero training updates and zero native task children. The original evaluation remains 56 new generations, 47 native executions and 9 validation rejections with its existing NoUpdate decision. Original weights, panels, source identities, budgets, #6778 and #6780 are unaffected.

The pinned model and base cards declare Apache-2.0. This preparation separately retained the official Apache license text because the upstream file list did not include a LICENSE file. It did not create an upstream license file or claim that the separately fetched text was one. No credential files, paid APIs or remote code were used.

An independently named and licensed base, once completely acquired, would permit a separately frozen E3 experiment. It would not itself establish teacher complementarity, student improvement, multi-teacher fusion or a new foundation model. At this final state there is still only the previously available Qwen base for actual model execution.
