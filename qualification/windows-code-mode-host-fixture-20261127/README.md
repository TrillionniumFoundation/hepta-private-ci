# Deterministic standalone-host failure fixture

The original ee553 Windows run 46071295499 / job 140748585208 is retained in full. CLI passed in 13.4 seconds and exec-server passed in 23.4 seconds. Core failed 4 of 19 original shard attempts. No CreateProcessWithLogonW errors appear in the full log. The remaining failures were the original subagent-stop hook count and the code-mode failure fixture; the full gate remains open.

The code-mode case disables the optional process-host feature and disables in-process fallback. Its unchanged assertion requires a real standalone-host spawn failure. Before the physical binary bundle, the test implicitly relied on the host being unavailable. With the correct bundle, its default real host executes the original text('unreachable') script. All three attempts therefore failed the original assertion.

This change selects the same intentionally missing standalone-host program already used by the neighboring original failure controls. It retains both feature settings, the script, the exact failed-to-spawn assertion, and all original deadlines. An unintended in-process fallback still emits unreachable and fails the original assertion. No production host selection or policy changes.

source-relation.json binds the entire previous/current file and the sole insertion in this exact method. Removing that one insertion reproduces the complete original file byte-for-byte. The original three complete Windows targets and no-FLAKY gate remain required.
