# Original completed learning checkpoint exports

The tested Rust source is `34eacaec1c94032f4980807e4a6f7c3516a7dafc`, tree
`fdfed48155d664ef3f56c84a6972f2d746e46587`, based on
`ed1ea5691798a2dbffbbcc8216f2929e67724af7` in PR #5357. This evidence commit
changes no tested Rust bytes.

The existing retained and adopted actor tests export the production-coded final
NextUse checkpoint only after their actual publication, ordinary actor execution,
acknowledgement and cold-recovery assertions. They retain synthetic training,
evaluation and worker output; actual neural training and production learning
qualification are not established. ACK, model STOP and complete model training
remain different facts. All exported authority remains DENY_ALL / NOT_EXPORTED /
HOLD_NO_GO.

Runtime job `rog:1a1bc339416-138b0-d6` ran the five original selectors with the
unchanged `just test` wrapper and nextest local profile, original timeouts/retries,
CPU 200%, memory 8 GiB and two Cargo jobs. The source's 11,190 tracked entries
were byte-verified before and after. The command exited 0: five selected tests
passed, no selected test was skipped or retried, and 748 unrelated tests were
filtered. Fresh compilation plus tests took 455.949 seconds; the five-test run
took 15.011 seconds.

`native/result.json` preserves the outer collector's failure after the successful
command: it expected JUnit below CARGO_TARGET_DIR. The original configured report
was emitted below the isolated workspace's codex-rs/target/nextest/local directory.
`native/verification.json` separately reconciles that unchanged original report's
exact test names, timestamp, source, command exit and full log hash. The original
failed result was not rewritten and tests were not rerun to hide it.

Maintenance job `rog:1a1bc43c985-138b0-13e` then ran `just fix -p
codex-hepta-agentd --locked --offline` and `just fmt --base
ed1ea5691798a2dbffbbcc8216f2929e67724af7`. Both exited 0 and produced zero source
diff. As required by AGENTS.md, no tests were rerun after this maintenance.

The Chain continuation at `a172152d7ef789fec95b61fee1fc8a116b8d6185` (source
`981a80c4c33f6477d5fcdcd01a31b8ee4816e607`, dependency PR #809
`5f7eccf86e252cce67bf5dd6f614c1c7a1824e53`) retains the exact original exports
and checks one appended receipt, unchanged original prefix and the acknowledged
original use. Its 26 original native-reader + 25 original Selection-join + 13 new
completion-join controls passed. This structural association grants no independent
custody, authenticated owner identity, real model training, settlement or FinalUse.
