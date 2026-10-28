# Preserved audit report serialization failure

The first independent audit of the completed skill experiment exited with code
1 because the legacy semantic report writer grouped up to 500 records in one
part. The richer 216 skill phase records exceeded its 400000-byte output bound.
The auditor had written 57 check parts, containing 28467 checks with no false
check, but it did **not** emit a complete summary. This attempt is a failed
audit invocation, not an independently completed passing audit.

`attempt-01.tar.xz` retains every file produced by that invocation, including
all partial check parts and the original stdout, stderr, source identity and
process receipt. `RETENTION.json` lists every original file's exact byte count
and SHA-256 and verifies the archive's round trip. The four small original
process/source/log files are also available directly in this directory.

The repair adds a skill-specific report serializer that measures encoded bytes
and splits oversized batches while preserving every record, value and order.
The only change to the main audit module is its writer import. The legacy
semantic writer, all audit comparisons, source targets, protocols, training
budgets, model parameters and runtime source files remain unchanged. Two
invented-data writer regressions verify lossless reconstruction below the cap
and refusal of a single unrepresentable record.

The second invocation writes into a new directory. All 57 check parts from the
first attempt are byte-identical to their counterparts in the completed second
attempt. Its complete report is [AUDIT-skill-longrun.json](../AUDIT-skill-longrun.json),
and its exact process/source/log records are in
[skill-audit-formal-process](../skill-audit-formal-process/). The original
experiment files were not rewritten, and neither invocation trained a model.
