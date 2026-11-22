# Authentic N256 checkpoint profile through index 128

Status: **PRECOMMITTED RESOURCE PROFILE / HOLD / all_closed=false**.

This separately frozen successor consumes the exact index-32 originals from
#6936/#6937. For each of the ten authentic N256 lanes it first cold-replays the
archived index-32 checkpoint from the exact detached index-two input and parent,
then advances to fixed boundaries 64 and 128. Every new checkpoint is
cold-decoded by replay from the archived index-32 source and must reproduce the
same canonical bytes.

The single admitted attempt is capped at 8 MiB per cursor and 64 MiB across all
20 outputs. Its exact work ledger is 30 index-two relation recomputations, 900
row actions used to replay index-32 sources, 960 warm extension row actions,
and 1,280 cold extension row actions: 3,140 row actions total. It performs zero
tail checks, provider outputs, dynamic steps, exponential actions, Torch calls,
or optimizer steps.

This profile cannot establish a bound at the first possible authentic tail
check, index 537. It does not close resource admission, tail termination,
unique binary64 rounding, provider completion, arbitrary-history resume, N256
qualification, C2 full replay, HPCA custody, or production adoption. A success
only supplies two further measured authentic checkpoint sizes and costs; a cap
failure remains a real negative result and is not rerun under another key.

#6901 remains `UNKNOWN`; #6908 remains `RED_DUPLICATE_KEY`; #6913 remains
`RED_NONCANONICAL_INPUT`; C2 full replay remains 0/6; HPCA remains NoUpdate;
global status remains HOLD / `all_closed=false`.
