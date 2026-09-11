# `control.engineering` candidate sandbox security profile

## Status and authority ceiling

This document describes the source-implemented Lane G candidate boundary. A sandbox receipt is qualification evidence only. It grants no self-review, independent acceptance, merge, canonical selection, activation, promotion, release, deployment, runtime capability, external effect, owner consent, peer enrollment, credential propagation, or autonomous replication.

## Exact, metadata-free source materialization

`sandbox_candidate` resolves the admitted base commit and tree from a clean caller checkout. It enumerates the complete Git tree with NUL-delimited `git ls-tree` records and streams every admitted blob through `git cat-file --batch` into a new temporary workspace.

This intentionally does not use `git worktree`, checkout filters, smudge/clean drivers, or `git archive`. Consequently:

- the workspace has no `.git` directory or Git file;
- it contains no object database, refs, index, alternates, hooks, remote URL, credential helper, or shared administrative metadata;
- `.gitattributes` `export-ignore` and `export-subst` cannot silently change the source denominator;
- every materialized regular file and symbolic link is read from its exact Git object;
- unknown modes, gitlinks, devices, FIFOs and unsupported object types fail closed rather than being approximated;
- absolute paths, traversal, noncanonical UTF-8 paths, case-fold collisions and escaping symbolic links are rejected;
- entry count and total materialized bytes are bounded.

Candidate commands therefore cannot mutate the caller repository through a shared Git administrative directory.

## Complete candidate-state binding

Before mutation, immediately after the admitted mutation, and after every check, Lane G walks the complete metadata-free workspace without following symbolic links. Every entry is bound to:

- canonical repository path and case-fold identity;
- entry kind;
- permission mode;
- byte length;
- SHA-256 file-content or link-target digest.

Directories are included, so post-admission empty directories are visible. The changed-path set is an exact manifest difference, not parsed human-readable Git porcelain. It preserves spaces, text containing ` -> `, deletions, replacements, mode changes, symbolic links, untracked files, ignored-file equivalents and files created after admission.

The realized footprint must equal the one path declared by `add_file`, `replace_text` or `delete_file`, or the empty footprint declared by `no_change`. Every changed path must remain inside the envelope roots and outside protected roots. File count and a conservative before-plus-after byte budget are enforced. After checks, the entire workspace manifest must be identical to its pre-check manifest; any extra write fails closed.

## Candidate and check identity

Before materialization, the implementation recomputes the candidate identifier and semantic digest from the exact envelope, base commit and normalized mutation. It rejects forged state, changed-path declarations, prior receipt digests, or any authority flag.

A request must contain at least one nonempty, NUL-free argument vector. The ordered complete check set is canonicalized and SHA-256 bound into the receipt. Empty checks cannot create a vacuous denominator and are rejected before source materialization.

Check stdout and stderr are written to temporary files under a hard byte ceiling rather than unbounded memory pipes. Wall time, address space, process count, file size and file descriptor ceilings are applied where the host supports them. Launch failure, timeout, excessive output or a nonzero status prevents a passing receipt. Timed-out process groups are terminated.

## Strong Linux isolation

Only Linux with an actually successful Bubblewrap admission probe may issue `sandbox_tested`. Merely finding an executable never sets an isolation field.

The adapter uses a new set of supported namespaces, including the network, mount, PID, IPC, UTS and user namespaces. It clears the environment and exposes only:

- standard runtime roots mounted read-only;
- a metadata-free candidate workspace mounted read-only at `/workspace`;
- private `/tmp` and `/home/sandbox` locations;
- a new `/proc` and `/dev` view.

The caller checkout, caller `.git`, repository siblings, host home directories, root home, runtime sockets and credential directories are not mounted. The admission probe must successfully prove that `.git` and the hosted checkout path are absent and that the candidate workspace cannot be written. Every real check is launched through the same adapter. The caller checkout identity and cleanliness are measured before and after as defense in depth.

## Portable fixture mode

`require_network_isolation=false` exists only for deterministic regression tests on hosts without the strong adapter. It still uses exact metadata-free source materialization, a sanitized environment, bounded execution, complete post-check workspace comparison and caller-checkout comparison.

A successful portable fixture returns `fixture_tested`, never `sandbox_tested`. It is ineligible for independent review, integration eligibility, canonical selection or any product transition.

## Mandatory adversarial qualification

The dedicated workflow executes portable checks on Linux, macOS and Windows and strong checks on both the exact Linux head and the ordered prospective merge. It proves at least the following:

1. an empty check set is rejected;
2. an exact Git blob excluded by `export-ignore` is still materialized;
3. allowed `replace_text` and `delete_file` operations retain their complete path;
4. a canonical filename containing spaces and ` -> ` is not truncated;
5. a protected workflow written after admission is detected;
6. tracked and ignored writes to the caller checkout are detected in fixture mode and grant no sandbox state;
7. a forged candidate identity is rejected;
8. the strong adapter cannot observe the caller checkout or `.git` and cannot write the candidate workspace;
9. a nonzero strongly isolated check cannot receive `sandbox_tested`.

The workflow itself only installs and identifies Bubblewrap. The implementation's `_admit_bubblewrap` probe is the single source of truth for isolation admission, preventing a second hand-written mount policy from drifting away from the code under qualification.

## Receipt binding

`SandboxReceipt` binds the candidate and base identities, source tree before and after, ordered check results, check-set digest, candidate-state digest before and after, caller-worktree digest before and after, adapter identity, observed network and filesystem isolation, duration, pass/fail result, credential-environment count and an always-false authority delta.

A receipt with unavailable isolation, no checks, incomplete execution, state drift, source drift, an unrecognized adapter or any nonzero check is not strong sandbox evidence.
