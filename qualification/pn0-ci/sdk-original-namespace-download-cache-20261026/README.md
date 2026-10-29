# PN0 SDK repository-download cache interface repair — partial

The original published155 SDK workflow saved a repository download cache but never restored it. Its save condition read `cache-hit` from setup-bazel-ci, which declares no such output. The minimal successor adds a pinned restore immediately after setup and reads that restore output in the existing save condition. It preserves the exact original SDK cache namespace/key/prefix/path, nonfatal cache policy and pinned action; no action-cache trust is introduced.

Independent YAML and byte comparisons establish that reversing these two edits restores the whole original workflow. Every original job, permission, runner, environment, feature, build/lint/test step, concurrency and 60/20-minute limit is preserved. The GNU/musl target-binding gap is separate and remains open. Original complete logs and official 60-minute timeout annotations remain in the preceding dependency evidence archive.

This fixes a real source interface defect. Cache-hit rate, speedup and completion under the original 60 minutes are **UNKNOWN**; no hosted run, compiler or test was invoked to claim otherwise. Current retained CI must finish before a push that could cancel it. Exact paired source, actual-preview checks, Windows boundaries and all PN0–PN6 acceptance criteria remain required. `task_complete=false`, `merge_ready=false`, **NO_GO**.

`members.json` pins the ordinary historical archive, each exact source candidate and independent review. Every original member was read back; this is not runtime or resource qualification.
