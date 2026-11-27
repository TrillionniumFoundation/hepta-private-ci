# Windows ACL correction and retained native mechanism results

This ordinary merge combines root candidate `28445e8a6a7ff0a1d7399faaf2aa4ddce0de8a71`
with PR #6396 at `577c03b5524fd45814dc71c3b5d847562ba2c410`. Both histories
are preserved. The merge base is `93dd309eb57384e655096ac34d52fabd221d7ec9`.

## Functional correction

Fresh write-deny ACEs now enumerate write-data, append, extended-attribute,
attribute, DELETE and FILE_DELETE_CHILD rights. They no longer include generic
write's shared READ_CONTROL and SYNCHRONIZE rights, which also occur in generic
read requests. Existing broader denies remain unchanged. The new native test
checks that a fresh deny leaves a real file readable while all four mutation
opens are refused. All eleven ACL methods passed at the incoming source head.

The two production ACL files and all six new mechanism-support files are byte
identical to PR #6396. The merge keeps the root token implementation, elevated
admission guard, elevated refusal tests and original four-cell delete test
unchanged. It removes one identical duplicate definition of
`workspace_token_refusal_leaves_existing_files_unchanged` that already existed
in the root candidate, retaining the original method and all assertions once.

## Native evidence

The complete original GitHub artifact is `native-tests-original.zip`:

- Source: `577c03b5524fd45814dc71c3b5d847562ba2c410`.
- Run: <https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/43809668796>.
- Job: <https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/43809668796/job/133108263117>.
- Artifact: `14200257405`, 27,683 bytes.
- SHA-256: `f5adf8f324f6398b73a3c6b5cfeced1598f278b7c1257809f6d67431be0c9bd5`.
- Seventeen distinct Windows cases: sixteen passed and one failed, with zero
  skipped cases and zero reported errors. Source postflight remained unchanged.
- Six Python integrity cases passed. The separate legacy admission observation
  completed with zero permission cases and `permission_qualification=false`.

`native-result.json` enumerates every original JUnit result. The archive keeps
the complete JUnit, stdout/stderr, source snapshots, command records and failure
state. No failed observation has been removed or recast as passing.

The prepared-read/full-restriction owned-object experiment passed. It preserves
read access, denies four outside mutations and WRITE_DAC/WRITE_OWNER, allows the
intended workspace mutations, and keeps the protected child. Its controls also
demonstrate failure when read authority is contaminated, the active parent gains
FILE_DELETE_CHILD, or the outside file has a null DACL. This is an impersonated
owned-fixture experiment; it does not execute the actual elevated broker child.

The MIC experiment failed: case 2 and case 4 preserved the medium-integrity
outside objects and allowed workspace mutations, but still deleted the protected
`.git` child through its writable parent. Its original assertion remains intact.

## Merge validation and remaining work

The scoped native workflow retains the incoming seventeen exact named methods,
adds the prior three distinct elevated admission methods, and preserves the six
Python checks and legacy observation. It gathers independent observations even
after a test fails, then returns failure if any command or exact result check
fails. The explicit incoming selection prevents unrelated root token methods
from being miscounted as seventeen; the full required platform suites are
unchanged. Every one of its thirty-five source pins and the parsed Cargo.lock
remainder digest is rebound to the actual combined source.

Local validation parsed the workflow YAML with duplicate-key rejection, compiled
its embedded Python syntax tree, checked every pin against the merged index,
verified all retained source identities, and independently matched the original
JUnit names and archive SHA-256. `just fmt --base 28445e8a6a7ff0a1d7399faaf2aa4ddce0de8a71`
could not execute on this Linux workspace because `just` is unavailable. The
incoming eight Rust files already passed the exact incoming native formatter;
the combined source still needs its own formatter, Windows build, scoped run
and complete required CI results.

The elevated backend remains unavailable under the unchanged admission guard.
The original successful-launch, token-identity and deletion-boundary methods
may therefore fail. The incoming MIC assertion also remains a known failing
hypothesis. This merge repairs the real read-deny defect and preserves stronger
mechanism evidence; it does not qualify elevated filesystem isolation or
authorize retiring the remaining Rust branches.
