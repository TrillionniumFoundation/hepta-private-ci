# Published amd64 image observation

This separate bounded workflow observes the immutable image requested by the
retained failing e4 RBE spawn. It does not rebuild the newer Dockerfile recipe.
The requested manifest is
`docker.io/mbolin491/codex-bazel@sha256:0a8e56bfaa3b2e5279db0d3bb2d62b44ba5e5d63a37d97eb8790f49da570af70`.
The exact `rbe.bzl` Git blob must remain
`57e301ac776d9c7196e9c854bc6e27ce2718d886`; a different source definition refuses.

The original artifact is 13739510839 from run 42763764984, archive SHA-256
`75f0d66a9bed98b735a0149e6f097dafedbf146b0201616d23d13c85092ed33b`.
Its bounded decoder and retained failed-spawn observations remain unchanged at
`qualification/verify2-rbe-spawn-20261110`. That spawn requested the same image and
PATH. Its test exit 101 remains a failure; XML generation exit 0 remains bookkeeping.

The new native amd64 job checks out the reviewed head and pulls that exact public
manifest, binds its inspected RepoDigests and architecture to the local config ID,
and runs only that ID. It records the image default user, five candidate paths,
resolved executable, package query, executable hash and dynamic dependencies.
If available, OpenSSH must actually generate an ephemeral Ed25519 key, sign an
SSHSIG, verify the original message and refuse a changed message. Missing tools
return nonzero and retain the original result; there is no installation or fallback.
The probe has no network, a read-only root, dropped capabilities, bounded CPU,
memory, PIDs and tmpfs. The private key remains in removed-container tmpfs.

Command receipts preserve stdout/stderr, exit/error, timeout and timestamps.
Individual output files have an 8 MiB kernel limit; the pull, probe and job have
240-second, 90-second and eight-minute limits. All records, including failures,
are uploaded for 30 days. Image inspection and exact probe/source bodies are
retained with a SHA-256 manifest. No registry login or publication occurs.

This observes the published image on a native Docker host, not the actual
BuildBuddy executor filesystem, mount policy, user or cache. A missing tool in
these bytes narrows the diagnosis but does not prove every remote execution
detail. A successful probe cannot close the original operator target. The actual
remote target still requires a verified repair and its own complete test pass.
The rebuilt-image measurement in #5644 is a separate branch and identity.

Original scientific gates remain HOLD/NONE: genuine independent terminal labels,
complete historical and physical costs, frozen matched prospective comparisons,
coverage, error reduction and net benefit are not supplied by this engineering job.
No inherited workflow, production source, image pin, trust rule or test is changed.

Local validation: immutable-manifest substitution, architecture/OS substitution
and malformed config-ID refusal passed. Pinned Ruff 0.15.13 lint/format,
formatting AST equality including type comments, POSIX shell syntax and workflow
permission/checkout/artifact invariants passed. The sparse workspace has neither
the repository Rust workspace/justfile nor `just`; full `just fmt` could not run.
Docker is absent locally, so this commit makes no native image observation claim.
