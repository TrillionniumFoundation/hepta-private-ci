# Preregistered directory LIST bit diagnostic

Base: `53290f59f1485bc5caaadde4f9e135aeaa59a090`, tree
`f47643ca8fc7589a60f04f1761c064ff82f4a071`. Its four tests actually produced
two passes, two failures, fifteen completed deletion cells, 32 OS5 opens and
16 successful AccessCheck calls. Those failures remain failures.

## One added test, six new objects

The added test identity is
`list_factor::directory_list_bit_observations`. It uses six newly owned
empty temporary directories. Each pair changes only the target restricting
capability ACE's `FILE_LIST_DIRECTORY` bit (0x1). The same Full restricted token
and exact single restricting SID are reused. No privilege or token is changed.

| Pair | Parent DACL | Target WD mask | Target capability mask, first / second |
|---|---|---|---|
| Target | WD: FA without FILE_DELETE_CHILD | FA | DELETE / DELETE + LIST_DIRECTORY |
| NullParent | NULL | FA without DELETE | 0 / LIST_DIRECTORY |
| Neither | WD: FA without FILE_DELETE_CHILD | FA without DELETE | 0 / LIST_DIRECTORY |

WD is the ordinary identity grant, never a restricting SID. Zero-mask ACEs are
explicit in both new baselines to keep each pair's ACE structure constant. The
four original test functions are not rewritten to use those ACEs: their old
byte-exact source and policies stay in place. Parent policy is installed before
target creation.
Every new DACL is installed and read back on the same handle using the existing
strict fixture setter. No generic World-FA capability helper constructs the
NullParent or Neither target.

For each object, the test first issues the old DELETE-only, overlapped,
BACKUP_SEMANTICS + OPEN_REPARSE_POINT, all-sharing CreateFileW probe. It closes
every successful handle, then calls the original RemoveDirectoryW helper and
checks that namespace existence agrees with the actual result. Both first-arm
failures must reproduce OS5; the Neither pair must reject both opens and deletes.
The two positive-hypothesis arms record either success or OS5 without asserting
success in advance. Other errors, cleanup failures or changed controls fail the
diagnostic rather than being skipped.

For Neither only, both ordinary-identity deletion routes are also absent. After
all that cell's observations, namespace and negative-control assertions, and
after token.run has reverted and verified no impersonation, the test rechecks
that original identity and restores WD FA on only its own still-existing new
target through the same-handle setter. A separate `HEPTA_DELETE_LIST_TEARDOWN`
marker records this cleanup-only change; it is not an observation or deletion
success. The final explicit TempDir close must succeed. No measured ACL changes
between setup and the end of the observations; the sole restoration happens
after those observations and assertions. No user or system ACL is repaired.

## Read-only metadata and causal limits

Original-identity query handles request only READ_CONTROL and FILE_READ_ATTRIBUTES.
On each same handle the observer reads LABEL_SECURITY_INFORMATION and attributes,
requiring an ordinary, non-readonly, non-reparse directory. There is no full SACL
request, SeSecurityPrivilege enablement or label change. The observer never
changes an ACL; the separately marked owned Neither teardown occurs later. Inside
the existing impersonation scope, a TOKEN_QUERY handle records integrity RID and
mandatory policy. The existing descriptor/privilege AccessCheck observer also
runs, without changing the deletion access requested.

Complete token/parent/target metadata must equal across each pair. A mismatch
fails the diagnostic and forbids a single-factor interpretation. The label
bytes are recorded exactly; absent labels are not silently rewritten. These
endpoint observations are not an atomic namespace or kernel AccessState trace.

If adding LIST makes an operation succeed while its baseline and Neither
controls hold, that demonstrates conditional sufficiency in these fixtures.
It does not establish that LIST is universally necessary, that a different
non-delete permission could not suffice, or that arbitrary Windows commands
are confined. No outcome changes the original 18-cell gate or 40 refusal guards.
If the bit has no effect, this protocol does not authorize a bitmask sweep.

## Execution and accounting

The original nextest command, unchanged, runs `--lib` with its original four
CASES and no filter expression. The entire original four-case source file and
four-test/eighteen-cell verifier are unchanged. The new `list_factor` integration
target is a separate test binary with one test. A second command selects
`--test list_factor` and stores `list-factor.log`; its verifier binds both the
exact `codex-windows-delete-boundary-probe::list_factor` binary display and test
identity. Neither command uses an expression filter: each requires zero skips
and zero retries. The second command runs even after the old tests fail so the
planned observations are retained, but cannot clear the earlier exit failure.
The original twenty-minute workflow budget is unchanged.

The isolated probe library exports only qualification fixture modules, using
paths to the same repository implementation for token lifetime, DACL installation
and AccessCheck. Product modules still include these sources only under cfg(test)
and expose no new product API. Existing Dacl variants and their SDDL strings are
unchanged; the installation body is shared through `set_dacl_sddl`. The new test
passes an exact ordinary-identity/capability SDDL rather than a helper that adds
World FA. The existing anyhow/windows-sys dependencies move from dev to ordinary
scope solely to compile this fixture library. Versions, features, both Cargo
locks and the production dependency graph remain unchanged.

The unexecuted v1 candidate is retained as a rejected design: its Neither cleanup
lacked deletion rights, and nextest counts expression-filter exclusions as
Summary skips. These source-review defects are fixed here without changing raw
results or relaxing either zero-skip verifier. No v1 native run occurred.

Both source sets, this protocol and all command logs are pinned in the receipt.
`diagnostic_complete` means the six planned observations and controls completed;
it explicitly does not qualify the original matrix. Before its own execution,
this candidate has no native result.
