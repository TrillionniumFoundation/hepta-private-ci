# Remaining owned Memory fixtures on macOS

The original full-CI macOS job 126243659686 on candidate
c4023a27d00622382d8f23830fae93350252bf5f runs the complete Memory target:
261 passed, 11 failed, seven original ignored probes. Its complete Memory
failure excerpt and full-job byte identity are preserved here. This is a real
negative result, not a synthetic fixture or a current success claim.

Six H7 trajectory cases and four local-turn binding cases still construct
separate fixture roots through the temporary-directory alias. The cold
recovery test also passes that alias to its child process. The child exits 101
while opening its store, before reaching the required deliberate exit 73;
the parent's existing exit-code assertion correctly rejects the result.

Canonicalize only these owned fixture paths, including H7's two reopen paths
and the path passed to the crash child. Keep all existing bodies and assertions
beyond fixture path construction, including expected exit 73, pending WAL,
recovery refusal and exact before/after tree equality. The production prefix
of local_turn_binding.rs is byte-identical. SQL, dependencies, lock files,
production root admission, explicit symlink/junction negatives and all original
ignored declarations remain unchanged.

The prior complete three-host native target and original Clippy qualification
remain required with the same 30-minute budget. Because the local execution
environment is unavailable, a separate hosted job runs the required original
just fmt on the changed files and rejects any resulting byte difference. It
does not amend the candidate or substitute for native tests. No local Rust or
formatter success is claimed. Keep Draft / HOLD_NO_GO / DENY_ALL until the
new source's actual gates are independently inspected.
