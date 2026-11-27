# Windows unsharded sandbox helper resolution

The original complete Windows run 46039259473 / job 140642486749 is retained in ancestor 0032154409d4b3036a3964e454940314f3d0d48e. Its CLI case and all eight exec-server failures report the same setup-helper launch error: program not found. The failures occur before the requested sandbox filesystem operations.

The prior declared helper binaries were available as data. The PATH materialization added to the Windows workspace launcher was used by the sharded core target, while these two unsharded targets still selected direct rust_test. This change explicitly selects the existing runfile environment wrapper for those two complete targets. The wrapper retains the entire original integration CARGO_BIN_EXE map and adds the declared setup and command-runner entries. It resolves absolute runfile paths through the existing launcher, preserving Windows separators and quoted paths.

No Rust production lookup, permissions, no-follow behavior, test method, assertion, budget, sharding configuration or retry policy changes. The original three complete Windows targets and strict rejection of FLAKY or retried attempts remain byte-for-byte identical in the workflow job. The workflow is enabled on this isolated successor branch.

Actual just fmt completed successfully. The ensuing original Windows run is required; this source preparation does not claim that its tests passed.
