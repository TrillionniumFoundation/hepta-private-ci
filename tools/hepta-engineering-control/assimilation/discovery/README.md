# Scoped Debian discovery implementation

This source materializes the `assimilation.discovery` target declared in
`docs/readiness/READINESS.json`, under the existing engineering-control owner.
It is the bounded metadata-reading sub-slice of `ASM-1-DISCOVERY-MANIFEST`, not
completion of ASM-1, the Debian bridge, external-system admission or federation.
No canonical readiness, source-completion or capability claim is advanced.

## Host interface and trust boundary

On Linux with Python 3.11+, the host calls `discover(root_fd, scope)` after it has
authenticated an enrollment receipt and opened an isolated, frozen rootfs. The
scope binds root device/inode, host and enrollment references, expiry, a fixed
os-release path and <=64 explicit service paths. These digest strings are NOT
credentials and cannot prove enrollment, revocation or isolation by themselves.
The host retains those responsibilities and must reject revoked scopes.

```python
from assimilation.discovery import DiscoveryScope, discover

# root_fd and scope come from the existing authorized host boundary.
# No absolute root path, shell command or unbounded file list is accepted here.
candidate = discover(root_fd, scope)
# candidate.payload and candidate.sha256 are immutable inventory candidate bytes.
# A separate typed adapter/reviewer must admit a canonical external manifest.
```

For a real process boundary, the same reader is available as a module command.
All operational inputs are mandatory; there is no current-host default, unit
enumeration or recursive discovery:

```sh
PYTHONDONTWRITEBYTECODE=1 python3 -m assimilation.discovery \
  --root /srv/hepta/frozen-debian-rootfs \
  --scope-receipt /run/hepta/discovery-scope.json \
  --unit etc/systemd/system/example.service
```

Run it from `tools/hepta-engineering-control`. The scope input has schema
`hepta.assimilation.discovery-scope-input.v1` and exactly these fields:
`schema`, `rootDevice`, `rootInode`, `hostIdentityDigest`,
`enrollmentReceiptDigest`, `expiresUnixNs`, `osReleasePath`, and `unitPaths`.
The repeated command-line units must match the nonempty receipt list exactly.
The absolute root path must open to the receipt's device/inode. The input is
bounded to 64 KiB, must be a single regular non-symlink file, rejects duplicate
or unknown JSON members, and is read consistently before the root is opened.

The CLI does not verify a signature, consent, revocation, enrollment or rootfs
freeze. Digests are opaque references, not authentication. Success emits one
canonical JSON line with status `DISCOVERED_CANDIDATE`, the private candidate,
its digest, stable omission codes, explicit false trust checks, and
`authorityGranted:false` / `activation:false`. Rejection emits a JSON line with
status `REJECTED`, a fixed `error.code`, `partialCandidate:false`, and the same
false authority/activation fields; stderr contains only that safe code. Exit 2
means CLI arguments, JSON, shape or selection failed before discovery. Exit 3
means unsupported platform, root open, or reader-side scope/path/content/target
validation rejected; 70 means an internal failure. Standard `--help` is the sole
human-readable, non-operational exit. No output-file option exists, so this
command adds no write authority.

The default OS source is `etc/os-release`. The host may explicitly select only
`usr/lib/os-release` instead after resolving OS metadata precedence. There is no
automatic fallback that silently ignores an etc override, and no symlink is
followed. Service files may be selected only from `etc/systemd/system` or
`usr/lib/systemd/system`; duplicate names across roots are ambiguous and reject.
Drop-ins, aliases, generators, template expansion and effective runtime state
are not resolved. The returned coverage explicitly says selected metadata only.

## Actual operations and limits

All reads use descriptor-relative component traversal, O_NOFOLLOW and bounded
read-only descriptors. Nonregular files, FIFOs, hardlinks, changed identities,
cross-device paths, invalid UTF-8, excess fields, path escape and expiry reject
without returning a partial candidate. FIFOs are opened nonblocking and rejected
before reading. Every descriptor opened by this component is closed on failure.

Caps: os-release 16 KiB; package status 2 MiB / 4096 records; each service 64 KiB;
128 dependencies per relation; <=64 selected services; <=4 MiB aggregate content;
4096 characters per line. Exceeding a cap is rejection, not silent truncation.
A second read pass checks the exact content and identity of every admitted file.
This detects observable drift but is NOT an atomic snapshot or a defense against
privileged same-device bind-mount manipulation. The host must freeze and isolate
the rootfs. No process, network, recursive scan, package install, service control,
D-Bus invocation, credential read or remote peer enrollment is implemented.
Ordinary filesystem reads may update access time; content/mtime are not changed.

Package parsing distinguishes selection, error flag and installed state: held
installed packages remain present and reinstreq is preserved. Non-installed
records are counted separately. The unit parser retains only typed After/Before,
Requires/Wants references. Execution commands and free-form descriptions are not
copied to the candidate. Raw metadata stays untrusted and is only digest-bound.

Ordering uses canonical Kahn traversal of After/Before edges. Requires/Wants do
not create ordering edges. An empty dependency assignment does not erase earlier
dependencies. Unresolved referenced units and blocked nodes are explicit. Blocked
nodes include cycle dependents and are not falsely described as precise SCCs.
This partial graph must never be used as a service start/stop plan.

## Verification, migration and remaining work

`python3 -m unittest discover -v -s . -p 'test_*.py'` executes the disposable
filesystem and subprocess tests: actual reads, deterministic replay, bounds, retained package
flags, ordering semantics, symlink/hardlink/FIFO rejection, expiry, identity and
replacement races, no content mutation, safe output and descriptor cleanup.
The dedicated read-only workflow repeats the entire engineering-control test
suite at exact source and deterministic actual-base synthetic merge. Local test
success is not a passed-CI, live-host qualification or performance claim.

The candidate protocol remains private to discovery. Canonical manifest
conversion, source signatures/SBOM, effective unit/drop-in resolution, D-Bus and
runtime inventory, isolated service parity, effect-boundary grants, migration,
rollback, independent qualification and organ registration remain later work.
There is no persistent state to migrate or production activation to reverse;
rollback removes this unused additive reader and test files. Accepted inventory
publication remains owned by the existing canonical data writer, not this code.

Parsing references:
- https://manpages.debian.org/trixie/dpkg/dpkg.1.en.html
- https://manpages.debian.org/trixie/systemd/systemd.unit.5.en.html
