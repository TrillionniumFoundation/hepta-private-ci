# CPU policy experiment preparation

`src/cpu_policy.rs` supplies two reusable **proposal policies** for a future
three-arm experiment. It is not enabled in Agentd startup and does not supply a
Hepta/model arm. The policies do not install budgets, mint grants, create K/D,
open another writer, infer permission from a result file, or replay effects.

## Common rules and explicit parameters

These rules implement the experimental limits in Desktop
`docs/HEPTA_INTEGRATION.md` section 7 and `docs/VALIDATION.md` section 6.

| Input/rule | Concrete meaning |
| --- | --- |
| Kernel period | Original HOS2 `100,000,000 ns` period |
| `maximum_cap_ns` | Explicit caller envelope, `10..=100,000,000 ns`; the original bootstrap grant can be narrower and remains authoritative |
| Fixed arm | Explicit target `0..=maximum_cap_ns`, approached using the common slew bound; no identical-cap write |
| Feedback arm | Two consecutive accepted samples proving the same direction; increase for runnable CPU pressure, decrease for proven spare capacity |
| Per-change bound | `floor(maximum_cap_ns / 10)`; saturates at zero and the maximum |
| Sampling/proposal limit | At most one accepted tick per `1,000,000,000 ns`, using both trusted observation timestamps and local acceptance time |
| Observation age | Native usage **and independently collected demand** must be at most `2,000,000,000 ns` old and cannot be future dated |
| Observation identity | Same boot and observer space, `CLOCK_BOOTTIME` domain; monotonic CPU/event/revision counters |
| Missing information | Unknown wait cause produces no feedback proposal; errors retain the actual last budget by performing no fallback write |
| Event loss | A policy instance remains fenced after any nonzero dropped-event count. A later zero does not reconcile the stream |
| User pause | Explicit trusted pause sample suppresses proposals. A zero cap by itself is not interpreted as a user pause |
| Interference | A changed resource revision resets the streak; a changed cap without revision rejects the observation |

`CpuDemandSample` is input from a real trusted workload collector, not evidence
created by this module. It includes boot/space and sampling time, so fresh native
usage cannot refresh an old pressure classification. Each consecutive tick must
contain a distinct demand sample separated by at least one second. A caller must
record the collector binary/source, raw observation and wait-cause rule in the
experiment receipt. ReadUsage alone does **not** report runnable queue length,
I/O wait, lock wait or ancestor throttling. Low progress alone cannot be labelled
CPU pressure. This change does not manufacture those missing observations.

State is process-local sampling history. Restart clears a streak, not authority,
budget consumption, a retained delivery, event-loss reconciliation or an uncertain
effect. After loss, an embedding can create a new policy only after its actual
collector and original owner have independently reconciled their state. The
policy is deliberately not a serializable restoration authority.

## Original request and effect path

1. Obtain `AgentdHos2Usage` through the attached original
   `AgentdHos2Device::read_usage`, collect same-domain `CpuDemandSample`, and pass
   both to `CpuPolicy::propose` with a trusted current `CLOCK_BOOTTIME` reading.
2. `CpuBudgetProposal::original_request` performs another original ReadUsage,
   reads the clock **after** that synchronous I/O, and checks proposal age,
   resource revision, budget and lifetime. It delegates construction to the
   original `AgentdHos2Device::install_request` and returns the existing
   `codex_hepta_memory::Hos2InstallBudgetV1` type. The delivery sequence is supplied
   by the original durable operation owner; this adapter does not allocate it.
3. The embedding must prepare its immutable operation through the already
   attached `AgentdProductionWriterHost::writer()` and dispatch only through
   `dispatch_to_with_grant_provider(HOS2_DESTINATION_V1, receipt)`, with the
   registered original `ProductionHos2Target`. All existing K/D, outbox, CAS,
   signed grant and synchronous FinalUse checks still apply. Never replace that
   path with an ioctl, synthesized receipt or second authority ledger.

The preparation recheck is **not** a guarantee about time spent in a subsequent
async grant request or queue. Before enabling an actual benchmark runner, its
original synchronous consumer boundary must also reject expired observation /
proposal state after every await. This module deliberately does not claim to
have completed that runtime wiring, nor does it bypass that gap by submitting
directly to the device.

## What the three-arm runner still needs

The fixed and feedback algorithm bodies and original request preparation adapter
are now concrete code. The following are still required for a real comparison:

- A source-bound workload and demand collector, including wait-cause evidence,
  task IDs, warm-up and fixed initial budgets; the policy code cannot supply it.
- Original-owner embedding and freshness enforcement at the final consumer,
  using the same workload, fault schedule, authorization and resource envelope
  for every arm.
- The actual Hepta controller entry and frozen model/inference configuration.
  A synthetic Cart simulator, replayed action trace, or this feedback policy
  renamed “Hepta” is not the third arm.
- Whole-arm success/timeout denominator, latency, CPU, memory, inference costs,
  recovery and energy observations. Shared package RAPL and unmeasured external
  inference energy must be labelled unavailable for per-task energy comparison,
  not treated as zero or attributed to one task.

The Desktop comparison gate refuses complete-comparison or net-benefit claims
until those inputs and all three real arms exist. Source identity must use the
actual final Hepta commit/tree and policy-file SHA-256 after formatting and
integration; a branch name or this document is not a frozen source receipt.

## Validation

From the Hepta repository root on the approved Rust 1.96 build host:

```sh
just fmt --base 7ea3df4e2ebaaa1052f8e01169ef0b5763beeda9
just test --locked --offline -p codex-hepta-agentd --lib -E 'test(cpu_policy)'
```

`cpu_policy_tests.rs` checks proposal bounds, hysteresis, rate limiting, stale /
future/replayed/foreign observations, event loss, explicit pause, revision drift
and retained charges above a lowered cap. `cpu_policy_native_tests.rs` uses the
**existing explicitly scripted protocol fixture** to exercise the original
QueryAbi/ReadUsage parsing and original typed request construction. It asserts
that request preparation emits no InstallBudget frame and does not allocate D.
Those fixtures test code paths; they are not actual kernel execution, successful
three-arm trials, energy observations or performance measurements.
