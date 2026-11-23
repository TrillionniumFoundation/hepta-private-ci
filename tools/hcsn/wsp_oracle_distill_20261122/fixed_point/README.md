# Deterministic DIRECT stop

The optimizer in PR #6956 computes its next proposals from fixed inputs and the current point. Once a full sweep accepts nothing, the next sweep is identical. This benchmark tests stopping at that fixed point. The parent module and its frozen results remain byte-for-byte reproducible.

In alternating order over two passes on five real GEN checkpoints, the baseline used 1,290 objective calls and 41,280 policy DPs. The early-stop program used 170 calls and 5,440 policy DPs. Optimizer CPU fell from 14.559 to 2.005 seconds. The candidate's canonical weight identity and objective agreed with the original on every pair. This is a bounded work-saving result on deterministic unchanged proposal sets.

From this directory, with a git checkout containing commit `def96748960a30eaf917bd43a368cfddddfd547f` and POSIX `patch`:

```bash
mkdir -p original
git show def96748960a30eaf917bd43a368cfddddfd547f:tools/hcsn/wsp_20261122_next/vendor/data_contract.py > original/data_contract.py
git show def96748960a30eaf917bd43a368cfddddfd547f:tools/hcsn/wsp_20261122_next/soft_value.py > original/soft_value.py
patch -o soft_value_stop.py original/soft_value.py < early_stop.diff
python benchmark.py /path/to/Hepta_WSP_Next_20261122_Evidence.zip fresh-result.json
```

The archived and reproduced results include both evaluation orders, proposal hashes and all attempts. Run under ordinary Python with assertions enabled.
