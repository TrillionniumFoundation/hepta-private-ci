# Query-only PSEC support observation

This source candidate adds one bounded observation to the existing legacy
DELETE test. It has not been compiled or executed on Windows. It does not
change the production token, ACL, policy, command or expected result.

## Fixed operations and ownership

After acquiring the existing legacy-test mutex and before constructing its
runtime, the test loads only `processmodel.dll` with
`LOAD_LIBRARY_SEARCH_SYSTEM32`. It resolves four fixed names: support query,
version query, environment create and environment close. The latter two are
checked for presence only and are never invoked.
All queries run in the parent test process, not in the restricted child.

The support query uses the official Microsoft MXC binding at commit
`383933e9dd4a6b068670767f5926adbdba2de6c9`: `HRESULT (UINT64*)`.
The version query uses `HRESULT (DWORD, BOOLEAN*, DWORD*)`, with major 1. Each
available query is called at most once. Outputs and their original HRESULT
are retained; `outputs_valid` is true only for S_OK, and the version BOOLEAN
must be 0 or 1. Missing exports, load failures and query failures remain
explicitly unavailable or unknown. Unknown support bits are retained as raw
bits and are not interpreted as permission to launch.

The module reference stays owned during both calls. Its normal release occurs
once, before logging, with the `FreeLibrary` result recorded. A failure is not
retried. An early unwind still has RAII ownership. No PSEC environment owner,
policy buffer or child process is created, and no Create/Close-environment
function pointer is called. Loading a trusted system module and performing a
query are not claimed to be a globally side-effect-free OS operation.

The single `HEPTA_PSEC_SUPPORT` JSON record is capped at 4096 bytes including
the prefix and newline. It contains fixed names, booleans and numeric values,
without SID values, paths from the user, credentials or pointer addresses.
Logging failure does not overwrite the original test result; a later artifact
verifier must classify a missing or malformed record as incomplete observation.

There is no retry, timer, extra test or native command. The existing two-case
selection, eight controller commands, 20-minute job limit and zero retry policy
are unchanged. The existing five legacy actions, complete final tuple, outside
and `.git` assertions, 5-second child timeout and 10-second exit/drain deadlines
are byte-preserved. The number of synchronous queries is bounded; their latency
is not separately bounded beyond the existing overall job limit.

## What the record cannot establish

Export presence and support bits cannot establish that environment creation
will succeed, that this host is a supported deployment, or that the required
filesystem policy has the intended semantics. In particular, the record does
not resolve ambient ALL_APPLICATION_PACKAGES grants, read-only exceptions under
writable paths, parent DELETE_CHILD behavior, aliases or process descendants.
No observation can turn either original failure into a pass.

The separate ordinary-TokenUser fixture premise and the separate PSEC functional
backend design remain independent candidates. No host preparation, dependency
addition, PSEC installation, DACL mutation, fallback backend, public source
publication or native execution is authorized by this source document.

## Primary ABI evidence

* [Official MXC runtime bindings at the fixed commit](https://github.com/microsoft/mxc/blob/383933e9dd4a6b068670767f5926adbdba2de6c9/src/mxc-sdk/src/backends/process_container/common/secenv.rs)
* [Query support declaration](https://learn.microsoft.com/en-us/windows/win32/api/processmodel/nf-processmodel-queryprocesssecurityenvironmentsupport)
* [Version query declaration](https://learn.microsoft.com/en-us/windows/win32/api/processmodel/nf-processmodel-isprocesssecurityenvironmentversionsupported)
* [Windows-sys 0.52 LibraryLoader binding](https://github.com/microsoft/windows-rs/blob/3a605cba064b26f2a198ac58085f8c8836f47c38/crates/libs/sys/src/Windows/Win32/System/LibraryLoader/mod.rs)

The Learn support declaration names an enum without showing its underlying
width. This candidate follows the pinned official MXC u64 output binding and
does not use a third-party DWORD32 prototype. The current manifest already
enables the required LibraryLoader and Foundation features; no dependency,
feature or lock change is included.
