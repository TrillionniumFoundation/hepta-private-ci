# MEM8 repair checkpoint: source gates complete; native and owner gates remain open

Checkpoint: 2026-11-11 10:06:48 UTC.

The 69-path repair candidate passed `just fmt`, the complete old-name scan, caller self-test and complete caller verification on its own isolated source. The original job exited 0 with complete durable output and no timeout or retry. Its complete tree is `e253b99e0a5c3b3a680569da0d224fabff0781ba`. This candidate has not yet received native qualification.

## What was verified

The root fetched both source archives from immutable Git commits in full, checked every member and source postimage, and recomputed the base and candidate Git trees from all 14,043 candidate entries. The first candidate contains 68 changed paths and 239 archive members. The second contains 69 changed paths and 242 archive members. The second formatting run changed no bytes; caller verification scanned all 6,196 Rust files, and none of the 13 retired test names remained. Both runs preserved the donor's exact source bytes.

The second candidate adds the model-catalog fixture's explicit cache-readiness observation to the 68 reviewed repairs. It retains the original single HTTP mock and response assertions. It does not qualify new memory benefit, provider behavior or an owner restoration.

The root also fetched 15 original-evidence objects in full from `cf406b45b7309d14ecc379cfee7c911e2eca98a5`, verified all 156 members of five direct archives and 12 additional members of the nested original Mac archive, and checked every member manifest. It executed no archived program.

## Original failures remain visible

The original full Bazel run `42971470498` is terminal with 37 jobs: 20 successful, 12 failed, four skipped and one cancelled. The Mac Intel test step exited 3; its final target summary contains 16 FAILED targets, four TIMEOUT targets and three FLAKY targets. These are Bazel targets, not counts of individual Rust cases. The job was subsequently cancelled during cache saving; its clean-worktree step was skipped. The cancellation cause was not established.

The first independent lock preparation had the expected commit and tree but lacked nine tracked source files. Its clean-base guard rejected the checkout before the candidate overlay or any lock command. A detached numeric process exit was not observed. The separate v2 preparation uses a fresh clone and explicit promisor fetch and full checkout. Its original job and PID are recorded in `CHECKPOINT_REPAIR_V12.json`; its final lock result was pending at this checkpoint.

The Linux print-only zsh controls completed. Their observed candidate changes depend on the supplied PATH. They are not a reproduction of the original Mac CI child environment. The original Mac control attempt timed out while fetching its fixed binary and executed zero argv controls. A separate artifact-preparation request has a separately recorded identity and budget; it does not change the original failed receipt.

## Correction to earlier Mac interpretation

The original trace shows a resolved cwd-based program path and `argv[0]`, but it does not record the literal serialized `request.file`. The earlier assertion that the request was a bare filename is retracted in `integration-2ae/mac-zsh/REQUEST_FILE_OBSERVATION_ERRATUM.md`. The actual Bazel TestRunner PATH has six absolute directories. It does not establish the later zsh child's PATH. The original child PATH and literal request spelling remain unknown.

Startup and storage diagnostic candidates are separate from the 69-path gate. A diagnostic improvement is not a fixed failure. No timeout, assertion, adoption threshold or provider ignore gate was relaxed.

## Current boundary

The shared execution environment disconnected after the root completed the source-v2 archive verification. Original archives are already in Git and existing remote jobs retain their original identities. No remote job was replayed because of this disconnect.

The source PR remains at `2ae5215beaf8d7b7df111a090b82134beae2683d` at this checkpoint. No new scored memory-benefit actor episodes or provider requests have run. All ten scientific and original-owner adoption blockers remain open. In particular, the original admitted provider turn is still UNKNOWN; archive recovery is not full owner/effect recovery.

`ROOT_VERIFICATION_RECEIPT_V12.json` records the completed root checks. Source archives and their complete publication manifests are under `repair-source-v1/` and `repair-source-v2/`. Existing original failure evidence is retained alongside the new source-only results.
