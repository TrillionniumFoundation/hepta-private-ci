# Original native owner host validation, 2026-10-24

This archive retains actual command reports and losslessly compressed raw logs.
It includes both passes and failures; it is not native guest qualification.
The exact source commit and tree in each original result remain authoritative.
The publication commit does not replace those identities.

## Actual results

| Original run | Exact Hepta source | Result and scope |
| --- | --- | --- |
| hepta-socket-diagnostic-host-01 | bb886c81f876d26eaa26a3ae214f084edb0c5a70 / b6e172d933595b080be620fb1d7601a848dc4f9b | 23/23 host tests passed, zero retries, one test thread. Actual pinned compilation completed; the real expired-writer handoff took 42.804 s and retained-terminal recovery took 20.499 s. |
| hepta-root-qualified-exec-05 | Same bb886c81 source | 2/2 actual isolated Root tests passed: original two-generation canonical publication/install/recovery/Ready, and actual UID/GID60001 filesystem and original socket paths. |
| hepta-root-qualified-exec-04 | 9f581f04e3d650c18bebb741b569d8d86cd46dac / d674ad97659f07b56e3fd389c06f933b9594d79c | The original Rust controller creation-window test passed for actual UID60001 and three umasks. The Host control socket test failed with EACCES at its original Fleet/run path. The complete failed run is preserved. |
| hepta-root-qualified-exec-03 | b53003fc102032120faaf00887219dafddd3a9d8 / e965d4d2735486f2c1a59bd0f686014086e3ddd2 | 6/8 actual Root tests passed: five launchers and recovered registry rotation. Canonical connection and native socket permissions failed. |
| hepta-creation-wire-peer-stage-host | 9f581f04e3d650c18bebb741b569d8d86cd46dac | 9/10 selected tests passed. The 17-owner federation request retained its two-second budget but returned 16 deadline/cancel failures. Keeping the real owners alive did not close this failure. |
| hepta-native-disposition-export-host | b53003fc102032120faaf00887219dafddd3a9d8 | 1189 tests ran: 1187 passed and two failed. The strict Native lifecycle decoder failure was subsequently fixed and qualified; peer deadline behavior remains independently open. |
| hepta-continuity-connect-host-01 | f5be86d2f0d4bc602f2ea4097e5f0cc72490c1d1 / 11bcf723e42b42b0a9185844a5abfaef01387d36 | Compilation failed on two diagnostic calls absent from the actual Tokio AsyncFdRegisterError API. No tests ran on that source. bb886c81 corrects only that diagnostic output and the socket namespace. |

The bb886c81 23-test run compiled the original seven selected packages:
Agentd, Supervisor, Memory, Fleet, agent protocol, Contracts and Types. This is
not the older seven-package set that included State and the two authority
packages. Final regression must cover their union rather than compare the two
test counts as if their package selections were identical.

## Concrete fixes and remaining boundaries

The controller creates its file without group/world write permission, then
preserves its original final mode/umask behavior. The real pre-chmod test covers
the original write_new path. The Host socket fix grants the actual Fleet/run
parent Root:60001 mode 03770; Agent/run remains independently protected.
UID60001 can bind the original Agentd/Matrix/App sockets and cannot write,
remove or replace Root supervisor endpoints or modify the parent mode.

The strict Native lifecycle method decoder rejects unknown and duplicate method
fields. Original full-method compatibility and strict outer envelopes remain.
The original core keeps registry/lifecycle isolation and original pending HOS2
state through real lease expiry and ownership transfer.

The newer canonical Root test passed without changing its original 500 ms
session I/O limit or clock horizon. The earlier Unavailable failure has not been
independently attributed to a specific cause. The new pass does not rewrite
that failed run or prove an intermittent failure repaired.

No native Hepta guest has been qualified by this archive. The original static
ELF must still pass unchanged 8 MiB file / 16 MiB LOAD limits. Exact product
kernel build, altered-image negative boots, the four original CPU/fault cases,
the two v4 continuation cases, same-disk cross-boot recovery and interrupted
activation remain distinct execution requirements. Host/parser passes, a
successful compilation, or an expired-owner host fixture do not grant those
qualifications.

Root fixtures used only per-run trusted executable directories and bind mounts.
Their actual source identities, commands, exit status and unmount results are
retained. Actual executable hashes remain in each result; large executable
capsules remain at their recorded isolated host locations rather than being
substituted by a source or parser fixture.
