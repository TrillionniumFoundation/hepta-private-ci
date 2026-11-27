# Windows OpenSSH startup environment

The first complete four-target run at source 7a26a7ef58e7f8e0ac225a0a6e9afed66ed3fb90 passed all original shadow durability, terminal ownership, and contract targets. The operator target executed all 33 tests: 18 passed and 15 failed during actual Windows OpenSSH key generation with status 255. Its complete original job log is retained here without rewriting failures.

The test-only command factory already resolves System32 through GetSystemDirectoryW. It now obtains the actual FOLDERID_ProgramData with SHGetKnownFolderPath and sets ProgramData only on each OpenSSH child. The allocated known-folder result is freed on success or error. There is no process-wide environment mutation, guessed drive, changed key-generation argument, or altered signature verifier.

Primary source: PowerShell/openssh-portable latestw_all contrib/win32/win32compat/w32fd.c blob 4005ce72d9ec11abab88a92e7ca20d99cf2e0c67, init_prog_paths reads ProgramData and fatals if missing; w32posix_initialize invokes it before fd table initialization. API and GUID: https://learn.microsoft.com/en-us/windows/win32/api/shlobj_core/nf-shlobj_core-shgetknownfolderpath and https://learn.microsoft.com/en-us/windows/win32/shell/knownfolderid .

One new Windows-only control removes ProgramData from the child and requires the observed startup failure with no key files, then uses the independent known-folder value and requires actual OpenSSH key generation. The parent environment must remain unchanged. All original tests and the five independent OpenSSH interoperability controls remain intact. Windows validation is pending until the follow-up original four-target run completes; this change is not a full-matrix PASS.

Native validation: original just fmt and git diff --check completed with exit 0; original complete operator package ran 29/29 with zero skips (20.430091 seconds including build, 0.231 seconds test execution). Its unmodified full log is archived. The new environment-specific negative/positive executes only on actual Windows and remains pending until that original target finishes.
