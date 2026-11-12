# Bounded handoff evidence admission and recovery

**Draft / HOLD / NoUpdate. No model calls or memory-benefit episodes.**

The original MEM10 reader followed symlinks and read evidence files without a
size bound before parsing or hashing. The original four focused controls produced
three failures and one error. A separate malformed nested replay terminal also
raised an unhandled parser exception. Complete original logs are retained.

The repair bounds launch, request, stdout, admission, terminal, response and
header reads. It refuses symlinks and special files; checks regular-file identity
across lstat/open/fstat, uses no-follow/nonblocking flags where available, and
checks size and metadata before/after reading. Malformed, missing, changed or
over-budget retained evidence becomes UNKNOWN without another send.
The caller still provisions a trusted journal parent; this is not authentication
of source truth, namespace custody or remote model execution.

Final validation: **22 passed / 0 failed / 0 skipped**, including the prior
16 transport controls and six added boundary/recovery controls. Intermediate
failures are preserved, including a test-harness open patch error and the
malformed nested terminal exposed before its repair; they are not overwritten.
Tests bind exact source bytes at local commit `dd9cd1e7876d4b1fc1c869896748e3b2b9e04a1c`.
Repository `just fmt` then passed with both Python ASTs unchanged. Tests were not
rerun after formatting. Ruff check and diff checks passed.

[EVIDENCE.json](./EVIDENCE.json) binds tested/formatted identities and the complete
[raw-validation.tar.xz](./raw-validation.tar.xz), including failed and final
executions, exact postimages and formatting receipts. Every indexed member was
reopened and matched to its byte count and SHA-256.

The hard transport deadline remains a separate supervision stage. Original
provider settlement, trusted owner/source/effect recovery, new-source exposure,
full baseline comparison and real episodic net benefit remain unqualified.
