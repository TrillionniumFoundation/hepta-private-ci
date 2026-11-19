# Completed caller verification and second executor interruption

## Completed original result

The full caller scan on local commit
`723a2d763339a55833519417a5f99f4defa9f8e2`, tree
`63b36ed30394d135b481813b1020548d8cf628c5`, finished with exit **0**
at 2026-11-12 04:46:57 UTC. It ran for 2341.214759903 seconds.
The wrapper returned identical clean before/after source identities.

`completion-record.json` preserves all fields from the completion object
actually returned by the execution tool. This is a JSON reserialization of
that returned object, not a claim to have recovered the original file bytes.
The original command log was recorded as 234220 bytes with SHA256
`2ad85d70cb2f892d2188a959513e5889d732e50885283618f05b0fbc967642a4`.
The complete log had not been exported when the executor disconnected and
is not included here. Its digest is a retained observation, not the log itself.

GitHub counterpart `2540a651` has the identical verified tree. The later
strict-wire fix and ordinary integration source were not part of this scan.
This PASS does not replace the earlier real full-caller failures.

## Last native integration result

The last integration run actually attempted before interruption was local
`70e4fa67b5e9e300e5e37bcc02f3baaa90611034`, tree
`f5e7e38ce7d7b67de649bec0dee57a283291c955`. It exited **101 during library
compilation; zero tests executed**. Six real writer call sites still used
`.artifacts.lock()` after introducing the Initial readview:
three in `cell_q24_publication_root_stage.rs`, two in
`cell_q24_publication_driver.rs`, and one in
`neuron_v13_generation_update.rs`.

The exact recorded log identity was 23603 bytes, SHA256
`91c7d3b22ace5b6c1fe6871dae5dddc26bd35236cd6b90c2b75feb3455b536f1`.
The original log is also unavailable in the disconnected executor.
A local fail-closed repair, `4c5a022`, routes all six through
`writer()?.lock()`; Initial readviews cannot acquire a writer.
Its eight source-closure cases passed locally. It was **not natively compiled**.
No newer integration native run was started before the interruption.

## Publication and reconstruction boundary

Published Root-only head `106f5e41f2ff8421c5aad10eeb746d453ed00563`,
tree `23cfee51a9031ab64aade9649f630bcb29e09f44`, remains recoverable.
Its strict-wire before/after logs and JUnit are in the sibling
`strict-wire-validation` directory: 2 passed / 1 failed before the repair,
then 3 passed / 0 failed after it, with zero retries.

Later local formal readview, main, Observer, RunStart and integration commits
are not treated as remotely preserved merely because their SHAs are known.
The unfinished Observer guard cherry-pick was not a clean final tree.
New candidates reconstructed from retained complete source text must carry
new identities and fresh validation. No original raw log will be fabricated.

The configured alternate Linux executor checked out exactly the published
Root tree in an isolated new repository. It reports actual UID 1000.
That successful checkout is workspace recovery, not product acceptance;
it does not execute or qualify actual-UID0 Root cases.

Independent static review found a possible persistent-refusal gap when a
corrupt primary record cannot itself be decoded to persist Fenced. Restoration
of old finalized bytes in a later process must be tested. The proposed durable
refusal marker must precede even the primary store open/read, share the
primary's scope slot while binding the full target, use monotonically
checked attempts, and remain armed through all actual context and deadline
postchecks. Static review is not a native reproduction or a verified repair.

Complete ordinary **Adopt / NoUpdate / daemon plus Root cold recovery remains
0 / 0 / 0**.
