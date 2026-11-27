# SQLite home association after runtime initialization

## Observed failure

The two macOS main CI jobs at source `97ab00451799667faebac2c455a1e3176ebc90cb`
retained failures in realtime startup context, Exec resume and TUI state-backed
operations. The complete realtime logs explicitly record `SQLite home mismatch`:
the caller retained `/var/folders/...`, while the runtime stored
`/private/var/folders/...`. The same event then records filesystem fallback and
`has_recent_work_section=false`. The original failures and attempts are retained.

`StateRuntime::init` resolves the configured home before opening databases and
retains that canonical configuration for its queue and directory guards.
`list_thread_ids_db` and `list_threads_db` previously compared it with the
caller's original `SqliteConfig` using lexical equality. A valid alias therefore
lost the existing SQLite context. This is an implementation association defect;
changing every test's input spelling would conceal the affected call path.

## Candidate

Keep the exact-config fast path. On mismatch, resolve only the requested,
existing home and apply the same `AbsolutePathBuf::try_from` normalization as
runtime initialization, including its Windows path handling. Compare the
resulting `SqliteConfig` with the runtime's retained configuration. `SqliteConfig`
currently contains only that home. Failure to resolve, a different home, and an
alias retargeted to a different home still reject the association.

Both queries continue to use the existing runtime. This does not reopen a
database through the caller's alias or change runtime initialization, directory
permissions, dispatch locking, recovery checks, or any original test assertion.
It checks the requested canonical name against the name saved at initialization;
it is not a new inode-identity proof or atomic directory lease. The existing
exact-path fast path also does not revalidate a directory replaced at that name.

## Regression and qualification

One Unix regression creates a real private home and a real symlink, initializes
through the alias, and exercises both metadata-query entry points. Full stored
metadata exists only in SQLite; an invalid placeholder outside the sessions tree
cannot supply it through rollout parsing. The same case checks the exact-config
path, a different home, an alias retargeted to that home, a removed alias, and a
dangling alias. Rejected requests must leave the original row and placeholder
bytes unchanged, and must not create a state database in the other home.

This source candidate has no Rust build or native result before its own
qualification. It does not establish that every other macOS timeout has this
cause. The existing mismatched-config regression and all upstream authority
tests remain in place.

## First native qualification and fixture correction

At source `be271ddfa2a2d519a44112e4f176d2d8c3499c25`, the GNU and musl
rollout unit targets each reported 124 passing tests and one failure in the new
home-alias regression. Its first ID-list assertion received `Some([])`, not the
seeded thread ID. The complete original logs are retained.

The fixture set a title but left both `preview` and `first_user_message` absent.
`metadata_preview` therefore stored an empty string, while both existing list
queries require `threads.preview <> ''`. Receiving `Some([])` is consistent with
the association succeeding and the row being filtered; it does not establish a
failure to associate the alias.

The correction seeds an explicit nonempty preview and checks the entire row
immediately after insertion. The query filters, association implementation,
invalid rollout placeholder, all positive and negative cases, and final
non-mutation assertions remain unchanged. This fixture correction still needs
native qualification at its own source revision.
