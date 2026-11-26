# macOS release publication candidate

This candidate has not been compiled or executed. The original Fleet failures,
the failed consumer tests, and the prior metadata diagnostic remain evidence;
source review does not establish that a new macOS run passes.

## Observed problem and source boundary

The two retained macOS CI lanes each ran the Fleet unit binary and failed four
installation cases at `install.rename` with EACCES. Earlier creation, content
copy, file sealing, directory synchronization, and outer-directory sealing
completed. Agentd and Supervisor also reported permission errors, but their
logs do not identify the failing filesystem operation. They must not inherit
Fleet's exact operation diagnosis merely because they call the same installer.

The fixed Apple XNU sources below request `DELETE | ADD_SUBDIRECTORY` on a
source directory during ordinary rename, including a same-parent rename. The
residual POSIX authorization path maps the latter right to write access. The
installer previously changed that source directory to 0555 before rename.

- [XNU 11215.81.4](https://github.com/apple-oss-distributions/xnu/blob/d4514f0bc1d3f944c22d92e68b646ac3fb40d452/bsd/vfs/vfs_subr.c)
- [XNU 12377.1.9](https://github.com/apple-oss-distributions/xnu/blob/f6217f891ac0bb64f3d375211650a4c1ff8ca1ea/bsd/vfs/vfs_subr.c)
- [Apple rename manual](https://developer.apple.com/library/archive/documentation/System/Conceptual/ManPages_iPhoneOS/man2/rename.2.html)

These are public source references, not an exact kernel-binary binding for the
CI image. Both sources contain this authorization branch. Separate Darwin 25
controls successfully renamed a 0555 directory; their filesystem, ACL, and
other authorization conditions do not establish the CI cause. The candidate
addresses the explicit directory-write requirement without claiming that every
EACCES is thereby explained.

## Publication states

Only macOS changes. The staging directory is created with POSIX mode 0700;
the catalog parent's mode and ACL are not changed. Inherited ACLs remain outside
this mode-only claim. Programs, the manifest, and `bin` retain their original
sealed modes before publication.

The outer directory remains 0700 through the same-parent rename. The original
catalog validator rejects its owner-write bit, and `allow_release` cannot
produce a new allowance for this pending directory. After rename, the producer
checks the physical directory's device/inode, opens it, rechecks the opened
object and path, and seals through that file descriptor to the original 0555.
It synchronizes that directory and checks path identity again. The original
catalog-parent sync and complete catalog resolve still precede a successful
installer return. There is no path-based chmod of a replacement final object.

No directory handle is held across rename. The identity comparisons bind the
seal to an observed object; they are not an atomic namespace lease. Another
administrator, a writable catalog parent, inherited ACLs, or inode reuse can
require a broader ownership protocol. This patch does not claim to supply it.

## Failure and crash boundaries

Before rename succeeds, the original staging cleanup remains. Once rename
succeeds, error cleanup does not touch the final path or the old staging name,
which may have been reused. A seal error returns unchanged; a directory whose
seal was not applied remains 0700 and rejected. Its name is retained for explicit
administrator recovery, and a subsequent install does not automatically remove
or overwrite it. There is no retry or permissive fallback.

A crash before sealing can leave this rejected pending directory. If sealing
has completed but a later sync or identity check fails, the directory may be
sealed even though the installer returns an error. Durability across that crash
window is not established here. All errors return no `RegisteredRelease` and
the installer never creates a per-agent allowance.

These guarantees concern the normal catalog and allowance path for a new
installation. Public raw-path constructors, cached objects, same-ID deletion
and reinstallation with an old allowance, and direct embedded supervisor APIs
are existing wider boundaries. No consumer validation or fallback is changed.

## Required behavioral qualification

Three macOS-only controls use actual directory rename and the existing catalog
validator. A private seal callback makes one failure deterministic; it is not
an exported production hook.

1. Rename failure preserves a pre-existing nonempty destination and cleans only
   the unpublished staging directory.
2. A seal failure after actual rename preserves the rejected pending release,
   original contents, and an independently reused staging name.
3. The pending release is rejected before the real seal; after sealing it passes
   full catalog resolution, explicit allowance, and manifest/program bindings.

The existing Fleet tests and Agentd/Supervisor consumers remain required. No
timeout, retry, assertion, ACL, consumer gate, dependency, or non-macOS
publication order is relaxed.
