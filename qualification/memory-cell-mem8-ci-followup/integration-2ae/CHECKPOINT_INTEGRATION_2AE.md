# Original 2ae integrated CI checkpoint

This checkpoint preserves the completed executions on source `2ae5215beaf8d7b7df111a090b82134beae2683d`, tree `12159640adcf073b51f3837e75575e11f5c20233`. It does not declare the complete hosted CI gate closed. The original caller, Clippy, Linux musl fixture, and Windows failures remain failures; candidate repairs are being prepared separately.

## Verified original executions

| Existing scope | Actual execution | Qualification boundary |
| --- | --- | --- |
| MEM native owner | 11 memory + 6 Agentd + 16 protocol = 33 passed, zero failed | 420 / 782 / 0 cases filtered by the respective commands; all three commit/revoke/panic drain markers observed |
| MEM Python | 154 passed executions, 120 distinct IDs, 34 repeated executions across groups | Software and scripted mechanism checks; no model episodes |
| Architecture source head | 526 native + 138 Python executions passed, all 31 original receipts verified | Counts are command executions, not globally distinct capabilities |
| Architecture base merge | 136 Python executions passed; zero native executions in this lane | Separately identified merge commit has the identical source tree and explicitly requires source-head success |
| Architecture required aggregate | Completed successfully | This does not override the separate failing CI required context |
| Windows private | 34 distinct regular native cases passed; zero retries | Includes the original signed-credit case. Separate negative controls retain their expected failures; two repeated positive-control identities are not extra distinct cases |

The MEM source, CLI identity, full command lines, complete raw logs, before/after source states, and clean format/scoped-fix results are retained. No source-head result transfers to a later repair head. The qualification-profile feature case was not selected by the original MEM command set; an additional explicit command is under review for the repair workflow.

## Immutable downloads and independent verification

The root downloaded all four binary parts of `mem-architecture/` from immutable commit `f94aec4112bf9f9aa76cb9a99c312a468b0cba06`, reassembled the complete 1,521,116-byte archive, and verified SHA256 `95e0a3f8366123c95d5b5a01ecffeff5ea6cbd9df693b08a4d6adc0fade57311`.

All 261 archive members and 260 member-manifest entries were checked. All five original ZIPs passed their official size/digest and CRC checks, and every extracted member was compared with the original ZIP bytes. Four reviewed file-only audit scripts were replayed offline. All report fields matched; the native audit's explicit local reference path changed to the independent replay directory, with identical reference-file bytes and hash.

The 25-member original caller/Clippy failure archive was separately downloaded, verified, and retained. The earlier root readback at `eae8aefe6faaa8fd827471d285d68ff7e4238fb1` verified the 389-member cleanup history, 20-member final cleanup observation, and 13-member Windows private evidence package, with both reviewed offline verifiers replayed. These are evidence reads, with zero new native tests or model requests.

`mem-architecture/ARCHIVE.json` is the immutable prepublication manifest. Its `remote_publication: NOT_ATTEMPTED` records that earlier assembly stage. The subsequent actual downloads and their identities are recorded in `root-full-readback/ROOT_FULL_READBACK_AUDIT.json`; the prepublication file was not rewritten retroactively.

## Original failures and repairs in progress

- The privileged-caller scanner rejected a test helper lacking its own lexical `#[cfg(test)]`, although its parent module was already test-only. The one-line candidate subsequently passed a complete source-only scanner execution. That is a dirty candidate proof, not a passing original 2ae CI run.
- macOS and Linux Clippy rejected an async mutex guard held across await. A private one-permit semaphore candidate preserves the admission serialization and RAII lifetime; native execution on the repaired source is still required.
- Linux musl failed one of eight stdio fixture cases with `ETXTBSY` before its session assertion. The fixture writer candidate preserves the original script and assertions while keeping the writable executable descriptor out of the multithreaded parent process.
- Windows shard 3 recorded 255 passes and 16 failures among 271 unique native cases. The failed tests reopened files still locked by their original owners. Bounded same-descriptor observation paths are being reviewed; the locks and original physical-byte assertions remain required.
- Windows current reached its original 65-minute budget and was cancelled. Thirteen completed groups recorded 115 ordinary passes, one passed-but-leaked result, and eight failures. The partial fourteenth group has no passing summary, and the remaining five groups have no execution evidence. The leak is not relabeled as an ordinary pass or a ninth FAIL.
- Additional Windows Bazel failures include tests still selecting a legacy sandbox entry that intentionally fails closed. Tests and helper prerequisites are being reviewed without removing that production guard. Other core failures retain their own unresolved diagnoses.

## Scope that remains open

The original provider smoke remains 0 passed / 1 failed, with an admitted application turn but no observed terminal settlement. Physical request count and remote outcome remain UNKNOWN. It has not been replayed under a new identity.

This checkpoint does not provide new unseen-task benefit, a current exposure attestation, independent source or authority custody, original production-owner recovery, or external-effect recovery. The ten adoption gates remain separately recorded in the owner ledger. Production adoption remains HOLD / NoUpdate.

The completed cleanup applies only to the fixed eleven superseded component runs. All eleven are terminal/cancelled; cancellation is not a passing test result. No integrated 2ae run was cancelled by that cleanup.
