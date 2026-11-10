# VERIFY exact-source CI and failed remote-spawn provenance

Source e4ba7c89eee20062d33303c95162e9796490d853 completed VERIFY run42763765025
on macOS129655332144, Windows129655332317 and Ubuntu129655332363. Each recorded
158 passing tests and9 scenarios/17 subprocesses. Its Architecture source-head,
base-merge and required jobs also succeeded. Full blocking CI remains failed.

The Linux Bazel artifact13739510839 was recovered in full (15,851,173 bytes),
with SHA25675f0d66a9bed98b735a0149e6f097dafedbf146b0201616d23d13c85092ed33b.
Provider reference: https://api.github.com/repos/TrillionniumFoundation/hepta-private-ci/actions/artifacts/13739510839
Its provider expiry is2027-02-08; the complete original ZIP has also been retained
as a separate companion file. The ZIP is not embedded in the small reference
archive. Signed download URLs are not retained in the repository.

The Bazel9.3.0 compact log contains277,928 entries. For the operator-acceptance
target, the actual test-setup spawn ran remotely, missed cache and exited101.
The same target's exit0 spawn is generate-xml.sh with the original101 in its
arguments. XML bookkeeping success is not a test success or a recovery.

Both declare the pinned amd64 container-image digest0a8e56bfaa3b2e5279db0d3bb2d62b44ba5e5d63a37d97eb8790f49da570af70
and PATH=/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin. These execution records
bind the requested platform. They do not independently inventory the container
filesystem or establish why ssh-keygen is unavailable. Changing the repository
Dockerfile alone is not a verified repair. Root cause and tool visibility stay open.

From a directory containing the exact original ZIP as bazel-linux-e4.zip, run
audit_spawn.py using Python3 and zstandard0.25.0. It verifies the input hash,
bounds record/stream sizes and extracts only the named target and selected
nonsecret environment fields. check_decoder.py validates one wire example,
seven malformed inputs and replays the original artifact. Parsed helper ASTs
remain unchanged after pinned Ruff formatting. No native test is skipped or
weakened; these are read-only diagnostic helpers with no execution authority.

reference-records.zip contains all three full VERIFY logs, original rbe.bzl,
the Bazel9.3.0 spawn.proto schema with original license and source/job/error
snapshots. MEMBERS.json binds every member. No original business effect or
model inference was replayed. cargo-deny still fails with unavailable log body;
other Bazel failures require separate diagnosis. Independent real-task labels,
complete costs and prospective scheduler net benefit remain OPEN/HOLD.
