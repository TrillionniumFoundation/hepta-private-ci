# Matrix socket classification: review proposal, not applied

The two original Matrix failures occur in `prepare_socket` before listener bind.
On Windows the current sequence accepts a connect error of `ConnectionRefused`,
then treats `try_exists == false` as an existing non-stale path. The original
fixtures start with a fresh path. No production Matrix or UDS code is changed
by this candidate.

## Smallest behavior change to review separately

After a failed connect, inspect the path with non-following metadata and keep
absence separate from an existing path. A precise `NotFound` from metadata may
proceed to bind without deleting anything. Other metadata failures must be
returned, not converted to absence through `Path::exists()`. An existing path
may enter the existing stale-socket validation only after `ConnectionRefused`;
other connect failures remain failures.

Conceptual replacement for the current failed-connect arms:

```rust
Err(connect_error) => match tokio::fs::symlink_metadata(socket_path).await {
    Err(metadata_error) if metadata_error.kind() == ErrorKind::NotFound => return Ok(()),
    Err(metadata_error) => return Err(metadata_error.into()),
    Ok(_) if connect_error.kind() == ErrorKind::ConnectionRefused => {}
    Ok(_) => return Err(connect_error.into()),
},
```

This snippet is not an applied or compiled patch. It does not certify that the
existing Windows stale-path check is sufficient: that implementation currently
uses existence, which does not establish owner identity or safe endpoint type.
An actual patch must retain refusal of live listeners, ordinary files, links,
junctions, unauthorized owners and ambiguous paths. A fresh-path bind and all
replacement races need real Windows controls. The companion Agentd control
function has the same classification shape and needs the same explicit review.

## Owner authorization remains a separate blocker

The current project's Windows `ensure_current_user_peer` returns `Unsupported`.
That describes this implementation, not an impossibility in Windows. The
official Microsoft AF_UNIX header retained in the source capsule defines
`SIO_AF_UNIX_GETPEERPID`; a future implementation still needs a fail-closed
connection/held-process identity contract, process birth identity and PID-reuse
analysis, TokenUser SID comparison, and complete error handling. Unknown identity
must never become success. Owner/DACL, reparse-point and crash-durability
guarantees are also required before activating the private-state backends.

The non-Unix permission and directory-sync no-ops in `prompt_runtime.rs` remain
unmodified and must not be activated by a partial registry port. No ownership,
symlink, stale-socket or durability check has been bypassed here, and neither
Matrix failure is marked closed.
