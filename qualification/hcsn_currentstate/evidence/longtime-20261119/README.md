# Complete-state cost over longer regeneration horizons

The five declared cases all completed within the original 120 CPU-second /
180 wall-second campaign limit. Their values and rate derivatives remain
accurate against an independent finite Gamma-renewal sum. However, the complete
pending release representation grows substantially even with one spatial state
and one retained packet. This implementation is an accurate bounded reference;
these results do not establish a constant-size or inexpensive long-sequence cell.

## Frozen model and independent reference

The scientific kernel is unchanged from local commit
`e4a49ce4a9234583b3c6d5e1af85cce74c048b3b`, SHA-256
`fccee9781c86af243c5f691f876d0dec34296edfedc327d6f4a100bcd2def949`.
The diagnostic source was committed before execution as
`e96fb40efc95428d49472b2ceb31ed3ae289674e`, SHA-256
`62daf4850b6e0079b5b75d50b57ba74a61ef76e75de9276f9caf3dd2172f502f`.

One active CTMC state has lower-hit rate lambda = 1.7, reset probability one,
no upper escape, and deterministic refractory duration d = 1/5. The initial
probability and signed-content channels are exactly the FP64 values 1 and -0.3.
The rate requires gradients. Discount is 0.15, active/escape reward zero, and
spike reward one; the quantities checked here are undiscounted expected hits,
active mass, refractory mass, and their lambda derivatives.

After each hit the process waits d and starts another independent exponential
active lifetime. Therefore the kth hit occurs at

\[
\tau_k=\operatorname{Gamma}(k,\lambda)+(k-1)d.
\]

For s_k = T - (k-1)d, the independent reference is the finite sum

\[
M(T)=\mathbb E N(T)=\sum_{k:s_k>0}F_{\operatorname{Gamma}(k,\lambda)}(s_k),
\qquad
\partial_\lambda M(T)=\sum_{k:s_k>0}
\frac{s_k e^{-\lambda s_k}(\lambda s_k)^{k-1}}{(k-1)!}.
\]

The refractory mass is M(T)-M(T-d), and active mass is one minus refractory
mass. The signed channel multiplies these quantities and derivatives by the
exact binary FP64 initial mark. The oracle uses 80-digit arithmetic and is
checked against a 50-digit calculation. It does not use the candidate generator,
matrix exponentials, or autograd. This is a finite CTMC reference, not a Brownian
or He-Xiong continuum-accuracy result.

## Observed results

Each row is one fresh Linux process, Torch 2.8.0+cpu, FP64, one numerical thread.
Forward includes `advance` and `refractory` with gradients enabled. Backward
is the total of six scalar gradient calls on that retained graph; it is not
the cost of a single combined network-loss backward pass. All cases end at an
integer multiple of the delay.

| T | T/d | Complete tensor bytes | Largest forward matrix | Explicit forward exponentials | Forward seconds | Six-gradient backward seconds | Lifetime peak RSS MiB |
|---:|---:|---:|---:|---:|---:|---:|---:|
| 0.2 | 1 | 192 | 4 | 4 | 0.033212 | 0.021555 | 219.758 |
| 0.8 | 4 | 816 | 10 | 13 | 0.018409 | 0.017773 | 219.168 |
| 3.2 | 16 | 9,072 | 34 | 49 | 0.022284 | 0.083147 | 221.012 |
| 6.4 | 32 | 34,416 | 66 | 97 | 0.034296 | 0.337393 | 225.578 |
| 12.8 | 64 | 134,256 | 130 | 193 | 0.134374 | 2.332774 | 258.586 |

Across all six quantities in all five cases, maximum absolute value error is
6.03962e-14, maximum absolute lambda-gradient error is 9.05942e-14, and maximum
probability/signed-content conservation error is 1.06582e-14. All values and
gradients are finite. No case was censored or retried. The whole campaign takes
13.502985 wall seconds and 13.402153 CPU seconds, including process startup,
imports, oracle calculations, serialization and controller work.

The state-byte column includes every tensor exposed by `State.tensors()`,
including repeated fields. It excludes Python objects, allocator overhead,
serialized metadata, and the retained autograd graph. RSS is the whole fresh
process high-water mark, including imports and the reference calculation.
Backward's internal matrix operations are not instrumented. The short timings
are individual observations, not a benchmark distribution or a throughput claim.

## Why storage grows

There is exactly **one** retained pending packet at each reported endpoint.
Its generator order is m = 2T/d: 2, 8, 32, 64 and 128. The packet stores m*m
generator entries, 2m alpha entries, m output entries and one reset entry;
the other state fields contain 13 FP64 entries. Thus this example's measured
logical payload is exactly

\[
8\bigl(m^2+3m+14\bigr)\text{ bytes}.
\]

The growth is inside a packet, even though packet count stays fixed. This is a
property of the implemented exact representation for this example, not a proof
that every mathematically equivalent representation needs quadratic storage.
It gives a concrete reason to investigate structure-aware compression or other
bounded representations, with explicit value, content and gradient error checks.
Discarding packets or reconstructing them only from current totals would change
the future release law and is not justified by these results.

## Evidence, resource limits and scope

The parent enforces a 45-second per-process wall cap and the total campaign
budget. Every child installs its 4 GiB address-space limit before importing
Torch, plus a CPU limit, and uses the unchanged work caps: matrix dimension
256, packet count 256, and 2,048 explicit exponentials. Source hashes are checked
before and after each case. These limits were not increased to complete a case.

`attempt001/REPORT.json` contains actual terminal codes, process costs, stderr,
stdout and child hashes. The five `case-*.json` files retain full references,
values, derivatives, errors, thread/limit settings and source hashes.
`REVIEW.json` records the independent read-only source/hash/formula review; that
review executes zero forward or backward calls. The original scalar-conversion
warning in each child stderr is retained. It occurs only when recording a
diagnostic scalar and does not detach the state used for subsequent gradients.

Reproduce using a new output directory from the repository root:

```bash
python -m qualification.hcsn_currentstate.study_longtime --output /tmp/hcsn-longtime-new
```

These results cover one fixed homogeneous one-state law, a signed content
channel and one rate derivative. They do not establish large-grid accuracy,
varying-input long-horizon stability, gradients through delay or event scheduling,
moving-boundary geometry, compression quality, task accuracy or a speed advantage
over SNNs, recurrent cells or attention.
