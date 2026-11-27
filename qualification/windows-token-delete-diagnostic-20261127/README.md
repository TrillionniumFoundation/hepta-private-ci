# Windows restricted-token deletion diagnosis

This additive test retains every byte of the three original token tests and leaves production token.rs unchanged. The original complete Windows sandbox target remains the gate, including both original failing outside-delete assertions. A diagnostic result does not qualify the product.

The diagnostic uses actual owned files and directories on Windows. It compares the existing production workspace token with an independently constructed all-access restricted control. Both have only the same capability in the restricting SID list. Each mode exercises four protected-DACL fixtures: direct file DELETE only, parent FILE_DELETE_CHILD only, neither route, and the existing explicit workspace capability permission mask. It records actual read/write, DELETE and FILE_DELETE_CHILD opens, WRITE_DAC/WRITE_OWNER opens, file/directory deletion, and final file existence. Main-user cleanup restores ACLs only on surviving objects created within this test's private temporary directory after impersonation has ended.

Microsoft's file-system check example independently tests DELETE on the target and FILE_DELETE_CHILD on its parent: https://learn.microsoft.com/en-us/windows-hardware/drivers/ifs/irp-mj-set-information3 . CreateRestrictedToken describes WRITE_RESTRICTED as limiting the restricting SID pass to write access: https://learn.microsoft.com/en-us/windows/win32/api/securitybaseapi/nf-securitybaseapi-createrestrictedtoken . The file generic access mapping is documented at https://learn.microsoft.com/en-us/windows/win32/fileio/file-security-and-access-rights . The exact Windows behavior will be taken from the actual diagnostic observations, not inferred as a completed fix.

The workflow runs the entire original windows-sandbox-rs-unit-tests target with one additional diagnostic method, nocache_test_results, the unchanged 60-minute job bound, and no test filter or retry relaxation. show-output exposes this successful diagnostic method's observations even when the original refusal tests fail. The original target's nonzero result remains a failure. No cargo dependencies, lockfiles, production source, or original assertion changed.

## Actual Windows terminal result

Run 46041979296, job 140651710122, finished FAILURE on exact aa736c2b.
The complete original target ran 152 original methods and one added diagnostic:
149 passed, two original refusal cases failed, and two original ConPTY methods
remained ignored. There were no filters or newly ignored methods.

Eight real protected-DACL observations isolate the cause. With the production
WRITE_RESTRICTED token, direct file DELETE is refused when the parent lacks
FILE_DELETE_CHILD. A parent-only FILE_DELETE_CHILD grant, however, permits both
file and directory removal while outside content writes remain refused.
An independent fully restricted token rejects both deletion routes, but also
rejects outside reads required by the unchanged original contract. Explicit
workspace capability grants retain their normal read/write/delete behavior.

The complete original log and all eight observations are retained. This is an
observed product refusal defect, not a passing qualification. Neither production
token construction nor the original tests or their assertions changed.
