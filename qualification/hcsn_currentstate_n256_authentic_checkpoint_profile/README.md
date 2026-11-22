# Authentic N256 checkpoint growth profile (HOLD)

This separately frozen diagnostic starts from the exact detached index-two
cursors archived by #6935 and their exact first-step parents archived by #6932.
For every one of the ten authentic lanes it advances the exact recurrence at
fixed boundaries 4, 8, 16, and 32, serializes all state, then cold-decodes by
replaying from the exact index-two input.  Warm and cold canonical bytes must
match at every boundary.

The fixed one-attempt budget is 50 index-two relation recomputations, 300 warm
row actions, and 520 cold replay row actions: 870 total.  It performs zero tail
checks, provider outputs, dynamic steps, matrix exponentials, Torch calls, or
optimizer steps.  Each cursor is capped at 8 MiB and all cursor payloads at
64 MiB; crossing either cap is a preserved failure rather than permission to
enlarge the budget.

This measures only exact rational state growth through index 32 on the ten
archived authentic requests.  It is not a tail/unique-rounding result, provider
completion, arbitrary-history proof, runtime or resource admission, N256
qualification, C2 full replay, HPCA adoption, or production adoption.
Historical RED/OOM/cancelled/UNKNOWN records remain unchanged.  Global status
remains HOLD / `all_closed=false`.
