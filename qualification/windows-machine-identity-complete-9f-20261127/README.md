# Original setup helper qualification at 9f971725

The complete original target passed: 28 tests, zero failures and zero filtered.
The sole outer ignored entry is the newly added subprocess worker. The parent
actually started it twice and required each process to exit zero with exactly
one passing test and zero ignored tests. Concurrent and later homes retained
the original machine credentials; the SID, Pending recovery and three real
private-file controls all passed. The full consumer matrix remains separate.

The original job log and complete verified artifact are preserved here.
The parent consumed both child outputs but printed only its summary. Therefore
this record explicitly does not claim that those two individual original raw
stdout streams were archived. This same commit adds logging of both actual
worker PIDs, exit codes, exact stdout/stderr bytes and commands. No production
code or assertion changes. A new run of the same complete original target must
supply those individual terminal records; they will not be reconstructed.
