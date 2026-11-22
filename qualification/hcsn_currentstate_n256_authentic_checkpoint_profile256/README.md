# Authentic N256 checkpoint resource profile at index 256
Status: **PRECOMMITTED RESOURCE PROFILE / HOLD / all_closed=false**.
This successor consumes the exact #6940/#6941 index-128 originals. Each of ten
lanes is cold-validated from its exact index-32, index-two, and parent inputs,
then advanced to 256 and cold-decoded to identical canonical bytes.

The one attempt is capped at 8 MiB per cursor and 64 MiB across ten outputs.
Its ledger is 20 relation recomputations and 5,080 row actions: 600 index-32
replay, 1,920 index-128 replay, and 1,280 each warm/cold extension; zero
tail/provider/dynamic/exponential/Torch/optimizer work.

This cannot reach the first possible authentic tail check at index 537. Its
result cannot close resource admission, termination, unique rounding, provider
completion, arbitrary-history resume, N256 qualification, C2 full replay, HPCA
custody, or production adoption.
#6901 remains `UNKNOWN`; #6908/#6913/#6939 remain RED; C2 full replay is 0/6;
HPCA is NoUpdate; global HOLD / `all_closed=false`.
