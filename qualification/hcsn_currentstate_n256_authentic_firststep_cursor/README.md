# Authentic N256 first-step cursor candidate

This separately frozen stage extends the exact #6925 initial capsule by one
bounded recurrence boundary only.  It reads the same immutable authentic input,
builds the two canonical operators, and for each of the ten frozen signed
vectors performs exactly one index-zero tail check and one exact row action.
Each resulting state is serialized and cold-decoded byte-for-byte.

The cold decoder reparses the complete frozen operator/vector/duration request,
rebuilds its transition, and validates the first-step coefficient, growth,
exponential-sum, dimensions, and partial-state identity.  It deliberately does
not execute a second row action.  The source contains no provider-completion
call and the admitted hosted attempt is limited to `GITHUB_RUN_ATTEMPT=1` under
the single key in `REQUEST.json`.

This does **not** qualify N256 provider completion, arbitrary recurrence resume,
large-grid full-state checkpoints, migration, Torch, optimizer recovery, C2
full replay, HPCA adoption, or production use.  #6901 remains numerical RED
with cause `UNKNOWN`; #6908 and #6913 remain RED; generic blocking results do
not transfer into this scientific scope.  Global status remains HOLD with
`all_closed=false`.
