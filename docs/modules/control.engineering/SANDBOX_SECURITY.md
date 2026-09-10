# `control.engineering` candidate sandbox security profile

## Status

This document defines the source-implemented candidate boundary carried by the Lane G closure candidate. It is a qualification boundary, not merge, activation, promotion, release, deployment, runtime, or independent-acceptance authority.

## Immutable source materialization

`sandbox_candidate` resolves the admitted base commit and tree from the caller repository, requires the caller worktree to be clean, and streams `git archive` for that immutable commit into a new temporary directory. Extraction is implemented by the controller rather than by a shell command and rejects absolute paths, path traversal, non-canonical repository paths, escaping symbolic links, unsupported entry types, excessive entry count, and excessive extracted bytes.

The materialized workspace contains no `.git` directory, Git file, alternates file, remote URL, object database, index, ref, hook, credential helper, or shared worktree metadata. Candidate commands therefore cannot mutate the caller repository through a shared Git administrative directory.

## Complete candidate-state binding

Before mutation, after the admitted mutation, and after all checks, Lane G walks the complete materialized tree without following symbolic links. Every path is bound to its canonical spelling, case-fold identity, entry kind, permission mode, byte length, and SHA-256 content or link-target digest. Directories are included, so a post-admission empty directory is not invisible.

The changed-path set is the exact manifest difference, not parsed human-readable Git porcelain. It consequently preserves spaces, ` -> ` text, deletion source paths, replacement paths, mode changes, symbolic links, untracked files, ignored-file equivalents, and files created after admission. The candidate manifest after checks must be byte-for-byte and mode-for-mode identical to the manifest before checks. Any additional write fails closed.

The only admitted mutation grammar remains `no_change`, `add_file`, `replace_text`, and `delete_file`. Its realized changed-path set must equal the mutation's exact expected path set. Changed entries must remain inside the envelope roots, outside protected roots, below the file-count ceiling, and below the conservative before-plus-after byte budget.

## Non-vacuous checks

A sandbox request must contain at least one non-empty, NUL-free argument vector. The ordered complete check set is canonicalized and SHA-256 bound into the receipt. Empty checks cannot produce a denominator and are rejected before source materialization.

Check stdout and stderr are written to temporary files under a hard byte ceiling instead of unbounded in-memory pipes. Wall time, address space, process count, file size, and file descriptor limits are applied where the host supports them. Timeout, launch failure, excessive output, or non-zero status prevents a passing receipt.

## Strong Linux boundary

A qualifying `sandbox_tested` state requires Linux and a successfully executed Bubblewrap admission probe. Merely finding an executable is insufficient. Bubblewrap executes with:

- all supported namespaces unshared, including the network namespace;
- a fresh session and die-with-parent behavior;
- a cleared environment;
- only standard runtime/toolchain roots mounted read-only;
- no caller checkout, caller `.git`, host home, root home, credential directory, runtime socket directory, or repository sibling mounted;
- a metadata-free candidate workspace mounted read-only at `/workspace`;
- private `/tmp` and `/home/sandbox` locations;
- an admission probe proving `.git` is absent and the workspace cannot be written.

Isolation booleans are set only after that probe exits successfully. Each real check is then launched through the same adapter. The exact source worktree identity is measured before and after execution as defense in depth.

## Portable fixture mode

`require_network_isolation=false` exists solely for deterministic unit fixtures on hosts without the strong adapter. It still uses the disconnected archive workspace, sanitized environment, bounded execution, full post-check tree comparison, and caller-worktree comparison. A successful fixture returns `fixture_tested`, never `sandbox_tested`; it is ineligible for independent review, integration eligibility, canonical selection, or any product transition.

## Mandatory adversarial regressions

The dedicated qualification workflow executes the following controls:

1. empty check sets are rejected;
2. allowed `replace_text` and `delete_file` operations retain the complete path;
3. a canonical filename containing spaces and ` -> ` is not truncated;
4. a check that writes a protected workflow after admission is detected;
5. fixture-mode mutation of the caller checkout is detected and grants no sandbox state;
6. the strong adapter cannot observe the caller checkout or `.git` and cannot write the candidate workspace;
7. a non-zero strongly isolated check cannot receive `sandbox_tested`.

Portable archive and fixture regressions run on Linux, macOS, and Windows. Exact-head and ordered-merge strong isolation regressions run on Linux. Unsupported hosts may validate fixture behavior but cannot manufacture strong-isolation evidence.

## Receipt and authority ceiling

`SandboxReceipt` binds the candidate and base identities, source tree before and after, ordered check results, check-set digest, candidate-state digest before and after, source-worktree digest before and after, adapter identity, network-isolation observation, filesystem-isolation observation, duration, pass/fail result, credential-environment count, and an always-false authority delta.

Neither the receipt nor its digest grants merge, selection, activation, promotion, release, deployment, external effect, runtime capability, or independent acceptance. Those remain separately authenticated and independently governed gates.
