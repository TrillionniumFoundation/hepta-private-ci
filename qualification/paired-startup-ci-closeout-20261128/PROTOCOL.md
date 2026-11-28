# Paired startup caller and test-helper CI repair

Source inspected: `0195e00d2883db5208de6cab8119cb6304b231c9`.
Publication base: its evidence-only child
`3871fbb62d4c3f69d07ce8651d488309c5363be8`.

The source-head hosted CI at `6eba6064ab0bed37ba5fe4654c7596bc18088b9b`
reported an undeclared original `seal_bytes` caller in
`authority_host_paired_startup.rs`. The existing startup implementation already
holds the original Root writer, checks current process and logind lifetime,
compares the exact plan before sealing, and rechecks authority afterward.
The manifest repair adds that exact existing caller to the closed set. It
does not broaden a call pattern, change the checker, remove a protected rule,
or add any production authority or runtime behavior.

Hosted Bazel Clippy also rejected `unwrap` inside non-test helper functions
in `root_cli_paired_tests.rs` and `production_terminal_owner_tests.rs`.
These helpers will return their actual errors; tests will propagate them.
Existing refusal, descriptor-closure, same-owner and live-fence assertions
remain. No Clippy suppression or replacement of failure with a default is
permitted.

The same hosted Clippy run also rejects three fixed UTC formatters and the
HTTP body-stream scope `expect`. The timestamp changes retain native
pre-epoch rejection, conversion to UTC, full Gregorian date representation,
second precision or three truncated fractional digits as before. They use
the existing Date Display and numeric fields, without an error fallback or
lint suppression. Source equivalence was checked against the actual locked
`time 0.3.55`, including signed years, extended positive years and fractional
truncation; `0.3.47` is the manifest requirement, not the resolved version.
The HTTP stream requires its same original scope and returns an internal
error if that invariant is missing; it creates no substitute scope and does
not change request admission, cancellation, or destination capability.
Dependency manifests and lockfiles remain unchanged.

Validation: inspect exact source changes, run the unchanged original complete
caller/protected proof against the complete fixed-source Rust inventory, and
run actual formatting. The single remaining drain control belongs to its
separate frozen `0195` gate. The one scoped `just fix` command retains its
prospectively reserved 220-second command cap plus 66-second wrapper reserve
inside the original 3,600-second engineering pool. This repair does not reset
that pool or any E1-E6 scientific ceiling, and does not rerun prior passing
native controls.

Other hosted CI failures are recorded separately until their actual cause and
ownership are established. A pass of this source proof or scoped lint command
does not establish all CI passing, a real training trajectory, user consent,
adoption, useful work, payment, or production qualification.
