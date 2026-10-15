# Research E3: convergence of independent model-source audit and resource-safe CI

**Lineage:** semantic merge of sibling research PRs #2315
(source-tree admission, parent `b782371435dddd2baf2425567d10662235f7250d`) and #2316
(same-branch CI deduplication, parent `46b55d48f34704a30a4f0c48b4f1786634fa7a9b`). The current
branch is a normal two-parent merge commit. No force push, reset,
retirement, or mutation of either sibling research PR has occurred.

This adds the original-source 192-row/128-fit-label filetree auditor and
all pre/post OCR and native Gemma2 execution receipts from #2315 while
retaining #2316's github.ref-scoped workflow concurrency and explicit
push-only physical jobs. Contract tests still run on same-repo PRs.
New HEAD has separate source-only runbook, both existing test suites
and a local integration source guard. Source/model/TEST-digest profiles
and `blocking-ci` are unchanged.

A passing source tree is not proof of a publisher signature, host
attestation or semantic image necessity. It is a byte-scoped model-entry
admission boundary. Passing the queue contract does not mean an
OCR/native physical job ran, nor that a cancel request changed global
GitHub Actions backlog. All historical negative science results are
retained. No production claim or model selection is made.

**DRAFT / SHADOW_ONLY / DENY_ALL / no main merge / no FinalUse.**
