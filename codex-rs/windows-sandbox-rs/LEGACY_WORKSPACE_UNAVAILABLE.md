# Legacy ambient-user workspace isolation is unavailable

The legacy ambient-user workspace token constructor and its preflight now return
`std::io::ErrorKind::Unsupported`. Callers must propagate this error. They must
not retry with the same ambient token, remove the sandbox, or label a failed
operation as a successful workspace capability. The dedicated-account elevated
backend and the existing readonly constructor retain their prior behavior; this
change does not qualify either backend.

Official Windows run `40366317884`, job `121725643044`, at source
`e483642459a58f7e18f9f4d317e3bc687bd0e24c` reproduced the original outside-delete
counterexample. The original impersonation token contained only the workspace
and temporary-directory capability SIDs as restrictors. Outside writes were
denied, but native access checks and file opens admitted the outside parent's
`FILE_DELETE_CHILD`. The child file's `DELETE` check was denied while the actual
`DELETE` file open and the original deletion both succeeded. Observation restored
all original source bytes and did not change the test's assertions.

Windows can authorize deletion through either the child's `DELETE` permission or
the parent's `FILE_DELETE_CHILD` permission. This fallback is documented in
[Microsoft's native filesystem security checks](https://learn.microsoft.com/en-us/windows-hardware/drivers/ifs/irp-mj-set-information3).
Removing `WRITE_RESTRICTED` also restricts ordinary reads outside capability
roots; those reads are part of the current contract. A lower integrity label on
the token alone cannot establish capability isolation from an arbitrary existing
outside directory with the same lower label. Neither change is a substitute for
a separately qualified native isolation boundary.

The new regression controls require that the constructor returns no token, that
the actual capture entry never reaches its process-creation wrapper and leaves
the command-start marker absent and outside bytes unchanged, and that preflight
refuses before creating its state or applying writable-root ACLs. The original
workspace tests remain unchanged and continue to report functional failure;
`Unsupported` is a safety refusal, not successful workspace execution. A future
native broker or separately confined identity must prove normal reading,
authorized workspace and temporary-directory deletion, and denial of outside
effects before this mode can be restored.
