# Windows retained Memory recovery on the current dependency union

Parent: 230d2d69a8c68ae6f8c502118fd9a8ee33027c37. This retains the original Memory migration ledger fix and the root owner's physical-path fixture repairs.

The source uses the reviewed retained Windows provider from e9cf924b88e3ace17e6fb74498949866f83a69d9 and the private-state foundation qualified at 052f4caa6c26396f37cecac6e133433d06a61eb2. Historical source is evidence for the candidate implementation, not a test result for this tree.

The port is limited to private local NTFS handles, existing-only frozen source observations, fresh private copy creation, and the Memory owner's real synchronization and admission path. The state boundary accepts only identical drive paths represented by Disk or VerbatimDisk prefixes; the remaining components must match exactly. Owner, protected ACL, reparse, local filesystem, file identity, single-link, source immutability, current-cut witness and writer-fence checks remain mandatory. Missing sidecar observation is not an atomic absence lease. Directory flush failure remains a failure.

The shared canonical path check already rejects redirection, so recovery preserves its accepted OS spelling instead of rejecting a lawful verbatim drive prefix a second time. Windows file and directory synchronization uses handles with the required write access and still calls real sync_all. Publication after rename can remain indeterminate and retains the candidate according to the original owner protocol.

The parent schema 1 through 15, schema oracle, all SQL, original assertions, original test budgets and seven existing ignored qualification probes are retained. The historical migrations 16/17, objective/HOS2 features, capture export, sender-store integration and new public close method are excluded.

New Windows controls exercise both native and verbatim home spellings through real retained SQLite inspection and writable current-cut recovery. An unrelated directory, different disk, different component spelling, UNC/device namespace and relative path remain rejected. An outside materialization target is not created.

The first hosted phase invokes the original repository formatter, actual Cargo metadata, original Bazel lock update and check. It verifies that the package/version/source/checksum set stays at the parent's 1,517 records and only the three listed workspace records gain their necessary dependencies. Any produced lock or formatting bytes must be adopted as a successor before native qualification can be claimed. No source-generation result is a product test pass.

Current state: DRAFT / HOLD. Original complete path, state and Memory libraries on Windows, Linux and macOS, scoped Clippy and original Bazel targets must run against the adopted exact source and locks. The four current Windows Memory failures, eleven parent macOS failures and seven originally ignored probes remain recorded in the independent original-evidence checkpoint cd0233bf700e411d30ee902b62b8ec7981f95e11.
