# Makepad composition CI runner-context follow-up

Source commit: `87b38cc0509a3050d5c03d433de6a1da79b4018f`.
Source tree: `f25b7f3066bfe56193c39c7138ddb7df49b47fa1`.
Parent: `a807c7bcc91158f3cc94de2c7ae0788680bdf104` from Hepta PR #3499.
This is the updated immutable source pin for downstream Desktop integration.

GitHub's [context availability reference](https://docs.github.com/en/actions/reference/workflows-and-actions/contexts#context-availability)
does not permit `runner` at `jobs.<job_id>.env`. The native composition job put `runner.temp`
there. The one-file follow-up removes that value and initializes the same target path from
the actual `RUNNER_TEMP` in the first source-binding run step, writing `GITHUB_ENV` for subsequent
steps. Missing runner variables fail explicitly. Paths remain quoted.

The two changed YAML scalar values are the only configuration changes. Triggers, same-repository
condition, matrix, original commands, required exact test names, source/lock checks and all Rust
sources are unchanged. In particular, none of the eight Rust tests has gained execution status.
The original `bb3a82cc6c4c24fae5fe62d83ff723afb6326224` source and its original evidence remain
retained; only this workflow blob changes from `80b8a0dd89e2c20bc14b4ca61c081e81b3befa69` to
`d9eb082eb9dd43ffbce94d748e7240ea9c307e8f`.

## Actual validation

The focused context check rejects the previous placement and accepts the revised one. The
YAML structures otherwise match, the exact patch applies and round-trips to the candidate
bytes, Bash syntax passes, and the full first run step exits zero in a temporary Git fixture
whose runner path contains spaces. Raw command stdout/stderr are retained, including the
host startup diagnostic from `/etc/bash.bashrc`; this is not a GitHub runner receipt.
Root independently verifies every job environment expression's root context against the
official table, exact source hashes and all 9,165 remote leaves/modes/blobs. No actionlint,
Cargo build, nextest run, native window or GitHub CI completion is claimed here.

The archive contains every frozen follow-up source/preimage, patch, preparation/validation
script, raw command record and root review/readback. Its inventory is fully decoded and
compared before publication. It contains no compiler outputs, SDK resources or dependency cache.
