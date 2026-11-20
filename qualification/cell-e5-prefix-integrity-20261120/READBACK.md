# E5 original source-prefix integrity

The v2 readout now keeps every original source position. The unchanged v1
counter evaluates `all(rows[:n])`, which can report a complete prefix for an
empty or shorter result list. The v2 target request places source refusals
outside its measured records; its historical jsonschema refusal is ordinal 13.
The new v2 entry checks the pinned original material index and source-prefix
manifest, validates the ordered measured/refused partition, retains that slot,
and requires complete original positions for each 1/4/16/64 prefix.

## Actual historical readback

The offline entry consumed the original request and original token result from
the archive published at `faeed277149701a316085a0453b05480df528655`. Both input
hashes matched the published evidence manifest before execution and remained
unchanged afterward. The 15 measured rows were retained exactly; adding the
original refusal produced 16 ordered rows. **All four static prefixes remain
false.** The 64-source point still lacks 48 materials and training remains closed.
`READBACK_RESULT.json` retains the complete new result; `VALIDATION.json` binds
the original commit, archive members, hashes, exact command and readback cost.

The original counter's measured cost remains 6.434541147 wall seconds,
5.593275237 CPU seconds and 707,268 KiB peak RSS in its byte-identical retained
result. The new offline readback took 0.062023543 wall seconds. These are separate
operations. This readback made zero tokenizer loads, model loads, forwards,
generations, gradient updates or upstream native replays.

## Source and verification

Fourteen focused standard-library regression tests passed before formatting.
They cover the exact old expression as a negative control, empty and incomplete
results, the missing ordinal-13 case, duplicate/reordered identities, strict
ordinal and boolean types, request/source/target/tokenizer bindings, complete
prompt/target bindings, original bounds, source-manifest tampering, actual CLI
use and target source-freeze coverage. An independent source review passed.

The original v1 counter, original source manifests, frozen experimental outputs,
source order and budgets are unchanged. The new target runner requires its own
actual source and the new helper to be included in a future source freeze.
Static context closure, optimizer/compute/verifier bindings and independent
future evaluation remain the original unresolved E5 requirements.
