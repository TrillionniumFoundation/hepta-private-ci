# Physical-home setup transaction

Original source 138979ef17182bbab90bb5bec0841e3dc9f35b1a / Windows run 46077877274 / job 140769775078 is preserved in full.
The CLI and exec-server targets passed; core was FLAKY with five retried shards.
The specific marker failure was CreateFile CREATE_NEW returning ERROR_FILE_EXISTS (80)
after concurrent setup helpers shared the same CODEX_HOME .sandbox marker path.
The other core failures remain separate unresolved work.

This candidate retains the existing marker removal, protected ACL, CREATE_NEW,
provisioning and final contents. A protected mutex now surrounds the entire
marker transaction and is keyed by the volume plus 128-bit identity of the held
physical directory. The handle refuses directory replacement; the open operation
does not create a missing leaf. The key uses an explicit HomeSetup domain separate
from machine credential authority. Different homes keep independent transactions.

Three new real Windows controls cover an independent process on the same directory
through its canonical spelling, an independent process on a different home while
the first transaction is held, and retained-directory / missing-leaf behavior.
The ignored worker is invoked explicitly by both process controls and each checks
its actual exit status and one passed, zero ignored result.

Actual just fmt and diff-check passed. Windows tests are PENDING at this commit.
The original setup-bin target and the three original consumer targets remain the
required actual gates, including all no-FLAKY checks and original timeouts.
