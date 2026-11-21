# Shared-parse signed batch candidate

Status: **SMALL SYNTHETIC PASS / AUTHENTIC N256 RESOURCE HOLD / all_closed=false**.

This candidate parses one exact signed operator and one duration once, then
evaluates five vectors with the unchanged exact-rational recurrence.  On the
small two-state fixture, the batch outputs and full per-vector certificates are
exactly equal to five independent scalar-provider calls.  The fixture includes
positive and negative inputs.  A separate zero-duration control includes a
negative-zero input and requires exact agreement with the scalar provider's
existing numerical-zero semantics.

The public candidate has a hard 16-vector cap and parses every vector before
starting any recurrence, so a later malformed vector cannot leave a partially
evaluated batch.

This stage does not load or execute the authentic N256 bundle.  It provides no
current host peak-RSS bound, wall-time bound, or valid allocation, so authentic
provider admission remains false.  It does not qualify N256/N512, current/full
state, migration, C2 replay, HPCA custody, production, or adoption.

#6908 remains `RED_DUPLICATE_KEY`; #6913 remains `RED_NONCANONICAL_INPUT`;
#6901's numerical cause remains `UNKNOWN`.  No historical negative or unknown
is renamed or removed.
