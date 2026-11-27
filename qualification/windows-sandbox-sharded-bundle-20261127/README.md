# Original Windows sandbox targets and sharded successor

The original source is 711e59801e51f063c777d1785354c029df1aa5fe. Run 46065846493, job 140730828591, naturally failed. The complete job bytes and original two-member artifact ZIP are preserved and verified here.

CLI passed in 25.8 seconds and exec-server passed in 24.5 seconds. Core failed 8 of 23 original shard attempts. Its workspace-root and hardlink cases still failed to start the sandbox child with Windows error 2: the original sharded test executable did not share the physical helper bundle already used by the two unsharded targets. Core also exposed independent agent-limit, notification-count and deadline failures; this change does not declare those closed.

The successor connects the same existing physical-copy bundle to sharded Windows integration targets which explicitly declare both sandbox executables. It preserves all Cargo binary mappings, the original workspace root, sharding and hash selection, test threads, commands, time limits and no-FLAKY gate. Non-Windows mappings stay identical. No production permission, no-follow or executable search policy changes.

The actual repository formatter completed with return code 0 in 0.27061512507498264 seconds. A fresh run of the same three complete Windows targets is required for this changed source. This evidence makes no whole-stack success claim.
