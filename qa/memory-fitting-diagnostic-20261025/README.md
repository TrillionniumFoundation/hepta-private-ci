## Fitting diagnostic after the failed retention screen

The single authorized diagnostic reproduced the seed-24029 failure **before
serialization**. The fitted model chose the wrong first value token on 31 of
40 training prompts. All 40 supervised-logit hashes matched exactly after
save/reload, and all 40 first-token choices matched between teacher forcing
and prompt-only prefill. This identifies incomplete first-token fitting at the
registered budget in this case; it does not establish an intrinsic rank or
capacity limit.

The new training run reproduced the original adapter tensor digest exactly.
Its 40 prefill first tokens also matched the original screen's 40 generated
first tokens. These controls connect the new diagnostic to the earlier 9/40
training-wording result without treating an old withdrawn checkpoint as usable
memory. The diagnostic loaded no old checkpoint.

### What was fixed before execution

The frozen configuration used fresh base initialization, seed 24029, rank 8,
completion CE, learning rate 0.001, and the original 256-update schedule. A new
local synthetic owner issued a new cell ID and `fitting-*` source IDs; its roots
were disjoint from all recorded old current and withdrawn roots. The original
textual scope, ten exposed facts, and forty training questions were retained
solely to reproduce the exact token inputs.

The reservation was 256 training forwards, 40 in-memory teacher forwards,
40 reloaded teacher forwards, and 40 reloaded prompt-prefill forwards. No
autoregressive generation, extra arm, retry, or eight-round extension ran.
Independent token/mask registration was checked against every actual public
forward call, including the original schedule, ignored prompt labels, value
targets, EOS, attention mask, cache policy, and stage order.

Canonical protocol digest:
`2fb9c95164e69d6418d5581ccda5432c9c01d17ec53b7886cc1320fe251297a4`.
All 59 current formatted source files and all fixed-base bytes matched before
and after execution. The source inventory digest was
`ca29e8cac677b926ca548b7ba6b073a9d5da33f09166d57dc96357c20e3c37e0`.

### Measured result

| Measurement | Result |
|---|---:|
| Correct first tokens, in-memory teacher | 9/40 |
| Save/reload supervised-logit hashes identical | 40/40 |
| Save/reload first-token differences | 0/40 |
| Teacher/prefill first-token differences | 0/40 |
| Largest teacher/prefill absolute logit difference | 0.0000476837158203125 |
| Original generation first tokens reproduced | 40/40 |
| First-token choice corresponding to the start of `silver` | 39/40 |
| First-token choice `white` | 1/40 |
| Correct later teacher-forced target positions | 56/56 |
| Correct EOS positions, included in those 56 | 40/40 |
| Mean final teacher completion CE | 0.9536003605 |
| Mean first-target negative log probability | 2.1490064055 |
| Mean later-target negative log probability | 0.0035769924 |

The observed target masks and causal positions were correct. The teacher first
token was read at prompt position `P-1`; prompt prefill used the final prompt
position. The later teacher positions receive preceding gold value tokens.
Their strong scores therefore do not measure free-generation quality.

The averaged completion loss includes easy continuation and EOS positions,
and each example is averaged over its own target length. It can look modest
while the entity-specific first token remains poorly fitted. Here, the two
`silver` facts supplied eight correct first tokens, and one `white` prompt
supplied the ninth. This is consistent with the dominant learned value prior
seen in the original screen. The evidence does not identify a unique optimizer
cause or prove that additional training or another objective will solve it.

The earlier retained-fact task scores remain valid failures. Because those
candidates were rebuilt from the fixed base, this diagnostic does not show an
existing adapter forgetting facts it had previously mastered.

### Actual cost and source withdrawal

The complete CLI took **206.990249708 seconds** under an external 600-second
supervisor. Two serial model children exited successfully. They used
**383.658712 CPU-seconds** in total and peaked at **1,160,944 KiB RSS**.
The counts were **376 top-level model forwards, 256 optimizer updates,
27,785 input tokens, and 808 supervised positions**. The supervised total
includes 616 training positions and 192 teacher-probe positions. Prefill had
no labels. No autoregressive generation occurred.

The adapter had 460,800 trainable parameters and 1,843,200 parameter bytes.
The last gradient allocation was 1,843,200 bytes; optimizer tensor state was
3,686,880 bytes. One saved checkpoint occupied 1,898,734 bytes. The complete
run directory contained 35 files totaling 2,594,382 bytes. The 5 MB rule is a
preflight/final-success gate, not a continuously enforced filesystem quota;
failure evidence is retained. Two-CPU affinity and Torch's two threads are not
a CPU-second quota or an independent RSS/cgroup limit.

After the probes, a real revocation of the newly issued `fitting-long_00` root
made the revoked-key read return `revoked` and the otherwise-live key return
`unavailable`; neither called the decoder. The current parameter binding was
unavailable afterward. Both children exited before 14:07:57.024693 UTC on
2026-10-25. Source and base bytes were reverified at 14:08:36.458684 UTC, then
the model/CPU lane was released.

The raw audit passed **2,269/2,269 checks**. Eleven pure checks passed before
freeze; an earlier test-only receipt-field typo was retained and corrected
before any model execution. The compact JSON companion binds the raw audit,
supervisor, source pins, implementation patch, and release receipts by hash.

### Remaining gates

This is one local development reproduction using already exposed facts and
training wordings, with a test-controlled synthetic authority. It provides no
new held-out, natural-domain, long-horizon, or downstream task result. It is
also not the default daemon process qualification. The earlier nine-trial
quality activation gate still fails, so the eight-round extension remains
unstarted. External production authority and the full future-task gate remain
open. Any further fitting intervention needs a separate fixed protocol.
