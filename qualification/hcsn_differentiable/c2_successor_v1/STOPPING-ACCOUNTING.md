# Recorded plateau and best-checkpoint accounting

The terminal controller now recomputes the original producer's stopping rule
from the hash-bound parent plan and the full retained metric prefix plus new
epochs. This closes the earlier explicitly disclosed missing plateau
recomputation. It does not rerun development evaluation or prove convergence.

The rule is unchanged: the strict maximum picks the earliest best epoch;
only score > anchor + plateau_delta resets stale_epochs. Stop at the first
epoch satisfying both min_epochs and patience. That plateau takes precedence
even when it coincides with the epoch cap. Later improvement cannot erase an
earlier stopping event. Explicit incomplete parent rows are rejected; legacy
parent reports without the journal's complete flag retain their existing
complete-prefix interpretation, with required metric/epoch checks.

Each epoch commit must contain its recomputed stopping state and select the
corresponding immutable epoch checkpoint or inherited-best object. The final
best.pt byte digest must agree with that selected commit object. Checkpoint
payloads remain opaque here: a different decoder/replay is needed to verify
their model contents, and metric values remain producer observations.

Actual isolated validation retained under the joint gate evidence directory:
11 initial controls against the old controller produced 8 real assertion
failures. The repaired suite passed 44 tests, then 46 after two legacy-prefix
controls were added. The complete joint source ran 95 unskipped test executions
and both existing probes with source unchanged. Existing 82-test receipts
remain tied to their older source. The new suite matches the actual frozen
c2_boundary.py prefix-state and first-stop functions on three delta settings.

No training, model inference, independent C2 replay or external custody is
performed by this gate. This is recorded-metric and entity consistency only.
Historical incomplete C2/UNKNOWN observations are unchanged. HOLD_NO_GO.
