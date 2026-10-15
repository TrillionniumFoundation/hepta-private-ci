# E4: observed training-resource frontier, original P0 → E1 → E3

**Research only / DENY_ALL / no model selection.** Stacked on E3 Draft PR #2362,
exact pre-E4 parent commit `dd025472d9f397fe8d3a0c0732b542fbca1ea069`.
Neither production Rust/Worker nor the original P0/E1/E2/E3 executors,
model checkpoint, human-label scorer or signing authority is modified.

## Why E4

E3 has a *learning curve*, but without a joint resource study it cannot tell
whether a smaller Stem and a gated Head reduce full service cost. A 4,145
parameter Head is not a full 4,096-cell service benchmark. Even Head-only
training costs vary with SGD, routing, setup and feature caching.

E4 performs a **read-only stdlib frontier census** after E3 original-human
source scoring. No additional pretrained weights, TRAIN/held source truth,
Torch or model loader enters this script. Original P0 full local process wall,
CPU, load time and peak RSS are kept separate from actual E1 new physical shared
projection, Head fitting and CAL/held inference scopes, and from the E3 second
shared projection and all three budget Head SGD scopes. All stages are
source/revision/digest/run-linked. The original physical Encoder forward
inventory must match the entire original FIT + blind source census.

### Explicit cost interpretations

- 
  **Stage sum**: P0 *whole model process* wall/CPU + E1 *substage* projection,
  Head fit and CAL/held + E3 *substage* extra projection and Head fit.
  P0 model load is INSIDE the P0 whole process and never double-added.
  Substages are measured in different jobs / sequential call scopes. Their sum
  is **not end-to-end service latency, comparable production TCO or a guaranteed
  wall-clock lower bound**. The missing E3 CAL/held inference and protocol
  lifecycle costs are not silently set to zero.
- 
  The theoretical FP32 Head weight bytes for 64,256,1024,4096 Cells are
  `N * 4145 * 4`, showing only resident *Head tensors*, not Encoder weights,
  activations, per-Cell state, token input, cache, routers, optimizer, allocator,
  transport, WAL or recovery. It is **not a 4096-Cell RSS measurement**.
- 
  The current Encoder's resident weight bytes and trained model identity are
  **unknown until independent target-host attestation**, even when the original
  P0 Runner reports a successful physical checkpoint and local model timing.
- 
  Full backward FLOPs, GPU/energy, p95/p99, nonlinear routing,
  FinalUse/CAS/CNS/control effects, restart and independently signed complete
  cost remain **unknown**, not zero or inferred from parameter count.
- 
  Eight original TEST source passages provide **descriptive task quality**;
  no 95% winner or time-disjoint future utility follows. All underperforming
  budgets/seeds, and budgets that cannot train two real classes, remain visible.

### Gates and evidence

Original pinned P0 V12 run `38686023757` at
`b3b3712828cb5814e1a87d1e69a030ec947c43c1` MUST first complete success.
E3's separate source-only model runners must finish 3 original pretrained
checkpoints, exact E1 refit/NumPy replay, E2 prelabel audit and physical E3
Head training/independent full NumPy replay. A different label-owning job must
replay original P0 human source and E2, then score E3. **Only after that** is
E4 cost reported. All source identities, sample census, shared projection
MACs/FP32 buffers, 3 seeds x 4 E1 arms, 3 budgets x 3 seeds x 2 E3 arms,
40 SGD update/exposure counts, human source budgets and independent E3 numeric
report/weight SHA must match. Missing cost evidence fails, not become zero.

Local verification used **synthetic CPU feature panels, fabricated cost
receipts as fixtures only**. No real pretrained task score, deployed model
cost, or production deployment is asserted. No experiment-result signer or
training authorization is issued.
