# C4 hosted W1 fresh-service: independent actual-artifact review

**Both finite business gates failed.** The original native test exited 0 because its assertion covers safety/accounting invariants; the fresh test exited 101 at its explicit four-second, six-depth business assertion. The original reader retained `CONFIRMATION_TARGET`, the fresh reader retained `FRESH_NATIVE_PROCESS_REQUIRED`, and the surrounding host child/controller exited 1. The fresh error label does not mean it was unexecuted: its complete native log records the actual failing assertion.

## Exact observation

- Chain source: `8df4b21d893906570d48f5beafabb3b31e0aefbc`, tree `6f5aaa2af0432e27e24b6bd2ad18013ab4423d14`.
- GitHub run `42076755695`, job `127418899990`, attempt 1, `W1 fresh challenge service (x64, head)`; completed with failure on 2026-11-05 at 23:16:56 UTC. This is the head lane, not the prospective merge lane.
- Actual artifact `13462092257`: 5,641,053 bytes; SHA256 `d1a8cf22fe723486d932a88c8401e3bbcc04c62ba5fc634732b012d763dcfa18`.
- All 57 regular ZIP members were fully read and CRC checked: 34,539,170 uncompressed bytes, including 15 actual empty members. Every file named by the original service manifest was independently hashed. The original ZIP, public API metadata, member inventory and exact selected members are retained in this delivery.
- The actual retained release ELF is 10,929,672 bytes, SHA256 `ab7cf9ead693a8d1da8cb737960ff8c360be96d6be6f5e4c4e401e05e92db9a1`. It matches build preparation and service before/after hashes. Exact command receipts and native logs are available; this artifact does not have the stronger held-FD/proc-image capture used in Hepta H4.

## Resource and source binding

Actual inside-before and inside-after observations bind the same root-owned parent cgroup, boot identity and installed unit. They record `cpu.max=25000 100000`, no CPU burst, `memory.max=2147483648`, `memory.swap.max=0`, and `pids.max=256`. The native child runs as UID/GID 1001 with no capabilities and `NoNewPrivs=1`. Host errors and final host errors are empty. This failure occurred after host preparation and real execution, not because the resource fixture was unavailable.

Both tests retain the original 4,000,000,000 ns traffic window and 16 attacker workers. The workflow remains the original 55-minute job. The separate native build preparation is outside the service-resource observation and must not be treated as a four-second service cost.

The original source receipts are identical before and after, recording 10,357 tracked entries and 985,270,534 bytes. This review made one read-only request for the exact immutable C4 tree and verified eight locally retained source files against its Git blobs, including both Rust tests, the host/binder/resource code, source verifier and workflow. It did not independently reread all hosted tracked bytes. The fresh Python runner's exact Git blob is bound in the tree, but its body was not locally available; this review does not claim to have independently audited that missing body. The complete actual reports and the available original host binder were checked directly.

## Independently recomputed outcomes

| Observation | Original retained-statement test | Fresh-statement test |
|---|---:|---:|
| Native exit | 0 | 101 |
| Attack-free confirmation latency | 2.287625131 s | 2.373093742 s |
| Attack-free confirmed depth | 6 | 6 |
| Legal submissions accepted under pressure | 7 / 7 | 7 / 7 |
| Pressure confirmation count | 0 | 0 |
| Pressure history pages replayed successfully | 3 | 2 |
| Next history replay | `PUBLIC_REQUEST_DEADLINE` | `PUBLIC_REQUEST_DEADLINE` |
| Failed replay ended, relative to traffic epoch | 4.050953811 s | 4.045973528 s |
| Attacker calls retained | 350 | 294 |
| Actual `WORK:Transcript` response refusals | 334 | 278 |
| Other failed client attempts, retained | 16 | 16 |
| Observed attack calls accepted | 0 | 0 |
| Finite business gate | **FAIL** | **FAIL** |

The original 16 constructed false statements retain 30 ticket trials and are reused by traffic workers. Fresh traffic retains 294 distinct challenge strings and packet indices, 575 ticket trials, and no exhausted construction. It is not valid to equate the two call counts to the same unique-statement work.

Original construction CPU is 4,129,631 ns and joined attacker-worker CPU is 239,841,632 ns; their distinct intervals sum to 243,971,263 ns for that reported scope. Fresh shared setup CPU is 56,504 ns and joined worker CPU is 315,562,840 ns, totaling 315,619,344 ns. The 90,091,781 ns of fresh construction is nested inside the workers and is **not added again**. These figures are not whole-system CPU or energy, and they do not establish globally cheapest legal work. CPU clocks, wall intervals, receiver work and independent replay remain separately scoped.

All observed attack calls were refused or ended in client errors, receiver work accounting closes arithmetically, and the original reports retain the safety/invariant flags. Those facts coexist with failure to provide the required confirmation in time. `overlap_demonstrated=false` is derived using a confirmation-end timestamp; when confirmation is absent it becomes false even though hundreds of real attack calls ran. It must not be read as evidence that no attack traffic occurred.

The failed local history replay is an observed boundary. The evidence does not yet identify a unique performance cause or prove a repair. There is no post-window retry/drain credit, resource increase, shortened load or relaxed assertion here.

## Qualification and audit limits

This is now an actual hosted failure of the fixed C4 service gate. The earlier desktop inability to establish the original hosted resource identity remains historical evidence, but it is no longer the only blocker. P0 public-service liveness remains **HOLD / failed observation** pending a real fix and requalification under the original gate. Single-host loopback tests do not establish independent operators, WAN acceptance, production activation or work-hardness qualification.

`review_zip.py` reads the original ZIP and recomputes counts, relevant predicate inputs, latency arithmetic, row coverage, source and resource bindings. It does not run the production reader, Rust, Cargo, CI, training, or a new benchmark. One exploratory display stopped on a legitimate `response:null`; that local analysis error is retained, and the final verifier preserves and counts every such failed attempt. The final independent review itself succeeded, which means the failure evidence is internally consistent, not that the business gates passed.

The input allowlist excludes every `download-reference.private.raw.json`. Temporary download URLs were neither read nor copied. Original H1/H2/H3 binary-read pause state was not touched.
