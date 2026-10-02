# Agentd retained run owner: reviewed Unix profile

The actual Agentd state now owns a retained run coordinator. Every mutation is
staged against the existing reducer, semantically validated, written and synced,
and only then published in memory or acknowledged. Released runs remain private
bounded deduplication tombstones; the public released-run status remains absent.
Same-composition recovery converts unresolved dispatches to indeterminate and
never redispatches. A changed generation/configuration is rejected until a
separately authenticated restart/reconciliation protocol exists.

The supported storage profile is Unix with a protected, trusted parent ancestry.
The retained parent must belong to the effective UID and must not be group/other
writable. All final file opens are no-follow and nonblocking; files require one
link, owner UID and mode 0600. Directory/file identities and current bytes are
rechecked. This is not protection against a privileged administrator or hostile
same-UID actor controlling the trusted ancestry.

Atomic create-new lock acquisition, rather than a prior stat, determines whether
bootstrap is allowed. A missing image behind an existing lifecycle lock refuses
reopening. The lifecycle lock is retained. There are at most 1024 active plus
retired identities and a 16 MiB image. A single create-new pending slot bounds
interrupted storage to the active and pending images. Pending bytes are never
overwritten or automatically trusted. A predecessor may reopen read-only, but
any required recovery write refuses until the ambiguous candidate is inspected.
No automated repair/destructive retirement procedure is supplied.

Non-Unix construction explicitly fails closed before storage I/O. Windows
Agentd startup through this owner is temporarily unsupported. A real retained
Windows file-identity/private-owner backend and native runtime tests remain
required before claiming restored Windows functionality or qualification.

## Evidence

- Independent final focused run: 26 passed, zero failed.
- Full affected package/product test selection: 188 passed, two failed. Both
  failures are Unix control socket bind EPERM in this execution environment;
  the actual signed product end-to-end path is therefore not locally accepted.
- Eight write/flush/fsync/rename/install error cuts preserve unpublished memory
  and poison subsequent acknowledgements. Eight actual child-process pre-ACK
  exits preserve either the predecessor or a durable indeterminate successor.
- Atomic bootstrap race, missing history, swapped symlink, nonblocking opens,
  shared parent rejection, retained identity and bounded pending cases pass.
- Scoped `just fix --locked -p codex-hepta-agentd --lib` succeeds with inherited
  dead-code/dependency warnings. `just bazel-lock-update` succeeds; only the
  existing libc package edge is added, with no Bazel lock drift.
- Canonical hosted Python selection: 727 passed. Canonical inference ownership
  keeps four required operations with typed executable bindings and separately
  preserves all 19 implementation details; no qualification gate is promoted.

This stage does not establish the typed cross-owner dispatch/abort/outbox bridge,
an atomic cross-process generation ingress fence, current-main acceptance, or
all hosted CI green. The draft remains stacked on the recovered inference base.
