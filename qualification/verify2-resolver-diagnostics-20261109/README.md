# VERIFY CI continuation: resolver failure is not proof of drift

All six original PR heads remain unchanged. On exact source
61d94bd6ac0b1d8f7c311d63e0112345538f1365, blocking run 42750867425 records
success for repo-checks build-test (129614028273), Codespell (129613905157),
and all three Native Hepta paths jobs. This independently verifies the five-file
format repair. Native paths are not the full 158-test VERIFY workflow.

Architecture source job 129613904152, run 42750867490, failed while downloading
the quinn index entry: curl error 56, connection reset by peer. The subsequent
offline resolver lacked that entry. The emitted lock-drift assertion therefore
does not establish actual lockfile drift. A single targeted source-job rerun was
requested after identifying this transient transport failure; its result remains
pending. Original job failure and diagnostics are preserved.

This increment changes only the misleading error annotation. The locked metadata
command, offline diagnostic, diff, checkout restoration and original nonzero
exit remain byte-identical. No retry loop, dependency update, advisory suppression,
permission change or weakened native check was added.

The archive contains two complete original decoded logs, the original workflow,
and PR/head/job/error snapshots, bound by MEMBERS.json. RESULT.json records the
scope and the exact one-line replacement verification.

Cargo-deny still fails; its current log again returned Transport closed. Other
Bazel failures remain separate. Full required CI and full VERIFY at a new source
head remain unqualified; ancestor passes are not transferred. Independent real
task labels, all historical/physical costs and frozen matched scheduler net
benefit remain OPEN/HOLD, with production authority NONE.
