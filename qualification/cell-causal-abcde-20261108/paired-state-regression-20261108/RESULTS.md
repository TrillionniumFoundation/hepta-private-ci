# Require the same actual initial state in D pairs

The paired D evidence validator now checks the canonical digest of the actual
before-state artifact in addition to the actual initial graph. Previously, two
individually consistent receipts could share a graph and declared contract while
starting from different state values. That pair was incorrectly accepted.

The exact original source at 6736d8ac reproduced the error for both split and
rewire cases. The corrected module passed all 7 tests, with no failures or skips.
The regression confirms that each individual receipt remains internally
consistent, the graphs are identical, and the pair is blocked specifically for
different actual state. Official just fmt followed the tests; no tests were rerun
after formatting. The source identities, original failure, successful results,
format records and closed admission guard source are retained in the archive.

This is a paired-evidence integrity correction. Unit-test signer identities are
fixtures. No real D experiment, new B training or E evaluation ran. The public
apply/recover entry points still reject missing Control lifecycle admission.
Scientific acceptance remains HOLD and benefit_proven remains false.

A real D run still needs the original durable Control owner, current anchor
CAS/readback and generation fencing, migration handoff ownership, independent
host/operator/observer custody, and actual successor consumption. Existing
journal and checkpoint mechanisms do not grant that admission by themselves.
