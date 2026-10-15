# E3 Five-Arm Actions queue decongestion (research only)

**Problem observed 2026-10-15:** the repository-wide Actions API returned
approximately 1,147 queued runs at the inspected instant. This observation
does not establish why GitHub is scheduling slowly and does not mean
that changing this branch can unblock the global backlog.

The prior research five-arm workflows used
`concurrency.group: ...-${{ github.sha }}`, despite
`cancel-in-progress: true`. Every new commit has a different SHA, so a
new push does not cancel older queued or running jobs for the **same
branch**. Both source-contract and physical workflows also ran on
`pull_request`, and both OCR/Granite and native EmbeddingGemma 2
physical jobs could execute on the redundant PR event.

This strictly research-only repair:

1. Uses `github.ref` as the stable queue group **within each
   workflow**. New pushes on the same research branch supersede older
   versions; different research branches retain different groups.
2. Retains source-contract verification on both same-repository PRs
   and pushes. Runs the expensive OCR, native EmbeddingGemma 2 and
   independent five-arm scoring jobs **only for push** to an allowed
   research branch. A skipped PR physical job cannot be used as
   evidence of a completed same-SHA run.
3. Keeps exact-SHA checkout, pinned source/model revisions,
   strict TEST label/digest quarantine, mandatory original model
   execution, 64 held-case coverage, Holm comparison, blocking-ci,
   original owner controls and DENY_ALL unchanged.
4. Adds a static negative guard for this specific queue behavior.
   No historical run is retrospectively counted as passing.
   Already queued runs using the previous SHA group are **not**
   expected to cancel retroactively.

This change reduces *duplicate new branch work only*. It never
approves cancellation of separate scientific branches and does not
create production authorization, a five-arm model winner, or any
independent source-ground-truth attestation.

**DRAFT / SHADOW_ONLY / DENY_ALL / no main merge, no FinalUse.**
