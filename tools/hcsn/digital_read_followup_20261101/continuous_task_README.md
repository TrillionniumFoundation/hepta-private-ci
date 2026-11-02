# Opt-in task adapter qualification

This stage connects the continuous numerical reference to the archived five
`first_passage_bank` artifacts at commit
`012bcf3505cb9306d9cef094a1acc3ca34c978be`. It preserves their fitted physical
parameters and their exact 48 → 32 tanh → 7 head weights. An explicit artifact
field must opt in to the new dynamics; an ordinary archived artifact is rejected.
The continuous reset distribution is a Gaussian conditioned on the open voltage
interval, with standard deviation `.12*boundary` and the archived fitted reset
centers. This is a different reset law from the archived folded finite bins.
There is no silent artifact migration and no new training.

At every action boundary the adapter evaluates the same nine free-endpoint
call probabilities at the actual continuous voltage, then normalized voltage
and lower/upper refractory flags. These twelve features plus the same 36 public
features enter the unchanged head. In refractory modes the call and voltage
features are zero. The head's belief is always its own learned output.
`fixed` uses the archived fixed-action rule. `structured_value` uses the archived
continuation outputs but imposes exact terminal score structure from that belief:
STOP=0, SUBMIT_0=1−2p, SUBMIT_1=2p−1.

For a nonterminal action, the previous completed observation determines drift
throughout the interval. First-passage events and recovery consume the true
remaining interval duration. Only afterwards does the real Python task Owner
complete a due read by opening the packet and running the frozen FullHX model.
Newly read content can affect the next action and interval only. Terminal
STOP/SUBMIT retains charged costs and cancels pending reads through the same
archived Owner semantics.

The qualification creates eight new IID task worlds per archived fit under its
own RNG namespace and executes both controllers, giving 40 worlds and 80 original
episodes. It does not read the separate control campaign's new models or
confirmation worlds. The source/protocol plus five explicit opt-in artifacts
are prepared and published before these qualification worlds are generated.

Each original action boundary, including initial and terminal boundaries, is
serialized to JSON with Owner state/receipts, actual continuous voltage, mode,
remaining refractory duration, PCG64 state, and public/artifact hash bindings.
Source, archived model, and opt-in artifact hashes must also remain unchanged
through the end of execution. The suffix is then executed anew from every such checkpoint. Every non-timing
field of suffix decisions and final checkpoint must exactly match uninterrupted
execution. Timing fields are retained but cannot be equal across actual reruns.
Full receipts, source opens, all interval event timestamps, charged costs,
checkpoints and replay suffixes are retained in `qualification/RAW.json.gz`;
all generated packet/public/evaluator files are retained alongside it.

This qualifies serializable state recovery at action boundaries in the same
Python process. The archived Python Owner has no durable crash/ACK transaction
API. The test therefore makes no cold-process, mid-action interruption,
exactly-once I/O, Rust parity, trained-controller quality, task-benefit,
energy-saving or production claim. Its new continuous inputs are outside the
archived finite training distribution, so observed utility cannot establish
that continuous dynamics improve that frozen head.

From the repository root:

```bash
python3 -m tools.hcsn.digital_read_followup_20261101.continuous_task_adapter prepare \
  --prepared tools/hcsn/digital_read_followup_20261101/evidence/continuous_task_prepared_final2
# Publish the prepared source/artifact freeze, then use its full commit SHA:
python3 -m tools.hcsn.digital_read_followup_20261101.continuous_task_adapter run \
  --prepared tools/hcsn/digital_read_followup_20261101/evidence/continuous_task_prepared_final2 \
  --published-source-commit FULL_40_HEX_COMMIT
```

Preparation and execution use exclusive output creation. Reproduction must use
a fresh destination rather than overwrite recorded evidence.
