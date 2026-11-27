# Flush the cold-resume fixture before sibling eviction

The cold-root resume test retains a worker thread object after that worker has
completed. Creating its sibling may evict the completed worker under the
existing resident-child limit. The eviction path shuts the writer down before
removing the worker from the registry. A retained thread object therefore does
not establish that its writer remains live after sibling creation.

Move the existing worker rollout flush immediately after the worker's completed
turn and configuration assertions, before creating the sibling. This ensures
that this explicit flush uses the writer while the fixture still owns its live
runtime. The existing residency limit, eviction behavior, sibling and root
flushes, shutdowns, new manager, cold resume, role assertions, thread IDs, and
environment assertions remain unchanged. No production behavior or test
expectation is weakened, and no retry or timeout is added.

This ordering hazard is supported by the test and writer lifecycle source.
It is not yet the established cause of the observed intermittent failure.
In the original 69-case selection at
`4497d4b5029b8e1a39a670e780f1722a09edc909`, 68 cases passed initially and this
case failed before passing its existing retry. That failed attempt emitted a
bare `thread ... not found` without an operation-specific context. Both
attempts remain evidence; the eventual command exit code is not a zero-retry
qualification. The original selection log SHA-256 is
`a5d7598f34604539777358d9b5b34310abef092b6149ee5df7c1d55928d6bab5`.

The preceding diagnostic source
`bacedfa0553b06f5952ef94ae979b939861336c8` adds phase context without changing
operation order. Its isolated native diagnostic remains a separate execution
under the original resource gate. This candidate changes only the test flush
ordering and its associated phase text; it does not rewrite that diagnostic
run's frozen source or claim a result from an execution that has not occurred.

`just fmt` and `git diff --check` pass, and independent source review found no
blocking issue. Native qualification of this ordering change is pending.
