# Legacy delete fixture observation

This is a diagnostic candidate for the existing
`unified_exec::tests::legacy_workspace_write_delete_is_limited_to_writable_roots`
test. It changes no production function, token, ACL, command, or expected result.

The original `bd5a42d` run executed both selected tests and failed both. The
factory test deleted outside objects. The legacy test instead left all three
writable-root files present, kept the outside contents and `.git` directory,
and reported command exit zero. Its old collector left the separate stderr
receiver undrained. These are distinct observations; neither establishes the other's cause.

## Fixed observations

- Retain at most 4,096 raw bytes from each child stream, 8,192 bytes combined.
  Count all consumed bytes separately. Only retained prefixes are decoded for
  the failure message; both rendered stream fields and counters fit in 50 KiB.
- Keep the original five-second process limit and ten-second exit wait. The
  original further ten-second stdout-drain wait now drains both streams
  concurrently under one shared ten-second deadline, without a new timeout.
- Before the original spawn, and after original exit plus output drain, inspect
  exactly nine owned fixture paths: the workspace, TEMP, TMP, and outside parent
  directories and corresponding files, plus the protected `.git` directory.
- Request only `READ_CONTROL | FILE_READ_ATTRIBUTES`, share read/write/delete,
  and open with backup-semantics and open-reparse-point flags. Capture attributes
  and owner/group/DACL from the same handle; close every handle before continuing.
- Bound each descriptor and the existing capability JSON file to 64 KiB, each
  DACL to 64 ACEs, and the capability maps to 256 entries. The descriptor logger
  has a separate 64 KiB total output budget and reports exhaustion explicitly.
- Classify ordinary allow/deny ACE masks, flags, and SID roles without printing
  SID bytes. Other ACE types remain explicitly unsupported. Read existing root
  capabilities only after exit; do not create, repair, or persist capabilities.
- Parent-process user/default-owner observations are reference labels, not a
  query of the launched child's token. Missing objects, unsupported data, and
  failed observations remain explicit. Raw SD byte equality is not a claim of
  semantic equality, an atomic snapshot, or absence of path changes.

The original complete tuple, five actions, factory test and fifteen records,
two-case selector, first nonzero exit, twenty-minute job, and zero retries remain
unchanged. No test is added. Synchronous reads have no promised latency bound.

This candidate has only formatting and source checks, no compilation or execution.
The parent `FILE_DELETE_CHILD` escape stays open. Separate fail-closed `Unsupported`
behavior is a safety disposition, not restored native filesystem isolation.
