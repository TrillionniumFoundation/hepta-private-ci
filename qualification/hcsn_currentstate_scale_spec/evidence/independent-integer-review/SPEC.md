# Static review of extending exact-support current state to graded grids

This review reads frozen `packets.py` at source freeze
`de3d9372d8bd53bb4c523c6f1a43e3e213d33790`, SHA256
`940c40f87a10c8a71d12fd6cb7c8cf7c77b8ec359f863394fd01eedc826a2ccd`.
It runs only a standard-library symbolic event graph and integer resource
arithmetic. It imports no candidate, numpy or scipy, constructs no spatial
matrix, loads no NPZ, and performs zero exponentials, quadratures or model runs.
It changes no legacy source or evidence. The current operator rejects the
proposed grids; the estimates are a counterfactual direct extension, not an
admission or a runtime profile.

## Intended binding and assumptions

The intended grids have interval count `N=128/256/512` and interior count
`n=N-1=127/255/511`. There are five independent linear channels: probability
and four signed contents. The parent supplied `L=8`, graded stretch `6`, actual
reset point `0.3131468965881033`, fixed delay `d=1/5`, and eight initial uniform
phase packets with disjoint supports `[j/40,(j+1)/40]`, `j=0,...,7`. Upper escape
is permanently active and nonreturning. This review has not independently
loaded that law or its numerical physics. The parent reports original N128
and N512 NPZ/JSON in the #6234 archive; the N256 export is missing and is a hard
input gate. No export is regenerated.

Dimension equalities below assume an irreducible spatial generator with a
nonzero lower selector, reset coupled to that generator, all eight phase
packets represented, fixed physics during the episode, and `T<=.36<2d`.
They use the current graph reduction, which does not prune a zero alpha or a
rare flux. A disconnected generator could have smaller ancestor sets; actual
source/input guards must establish the assumed graph before using these
equalities. No numerical matrix is needed to count this conditional graph.

## Block closure and dense storage

Let `s` be the sum of dimensions of the continuous packets releasing in the
current segment. The two active generations contribute `2n`, so the source
and active matrix has `m=2n+s` coordinates. Three upper origins produce an
extended matrix of dimension `m+3`. The undiscounted integral adds two hit
selectors, giving an exponential of dimension `m+5`. The discounted integral
adds five selectors, giving dimension `m+8`. Each flux-packet observation uses
two exponentials of dimension `k+1`.

An original uniform phase packet has dimension one. Its first-hit packet has
dimension `k=n+1`: that scalar source plus all first-generation spatial
ancestors. When that packet releases after d, `s=n+1`, `m=3n+1`, and the largest
exponential has dimension `3n+9`. The next-hit packet retains `2n+1` ancestors:
the incoming first-hit packet and the second active generation. The current
first active generation does not feed the second hit inside that segment and
is removed by the output-ancestor graph. First-hit packets produced after d
retain only the current first active block and have dimension n.

| Intervals N | Interior n | Phase first-hit k | Second-hit k | Source+active m | Largest exponential D | One dense D×D float64 matrix |
|---:|---:|---:|---:|---:|---:|---:|
| 128 | 127 | 128 | 255 | 382 | 390 | 1,216,800 B |
| 256 | 255 | 256 | 511 | 766 | 774 | 4,792,608 B |
| 512 | 511 | 512 | 1023 | 1534 | 1542 | 19,022,112 B |

Even without a releasing packet, the largest exponential is `2n+8`, not n.
Each packet stores a dense `k×k` generator, a `C×k` alpha, and a length-k
selector: `k²+(C+1)k` float64 values. The physical persisted arrays contain
`C(2n+10)` values. For C=5 this is `10n+50`; `R/Z` add another `6C` readout
coordinates but are reconstructed from the complete pending laws.

The implementation visibly holds C, its upper-extended copy, the first
integral result, and the second integral's augmented matrix and multiplied
argument. A conservative accounting of those visible dense arrays is
`8[m²+(m+3)²+(m+5)²+2(m+8)²]` bytes. At n511 this is 94,716,592 B before
pending matrices, numpy/Python headers, expression temporaries or scipy
workspace. This is a storage accounting, not measured peak RSS or a complete
allocator upper bound. Dense matrix dimension cubed is only an algebraic
scaling indicator; rates and the backend determine actual exponential work.

## Serialization lower bounds

The existing encoder writes every dense coefficient as a separate quoted
`float.hex` string, including all zeros. A finite binary64 hex string has at
least eight characters and at most twenty-four. For a nonempty array of L
values, strings plus separating commas therefore occupy at least `11L-1`
bytes and at most `27L-1`, excluding the array brackets. Across F values in A
nonempty arrays, the conservative contents lower bound is `11F-A`. Including
the brackets makes it `11F+A`. Dictionary keys, shapes, rational supports,
operator and physics identities, checksums and other metadata are additional.

There is no universal metadata upper bound for arbitrary exact Fraction
times unless numerator/denominator bit lengths are bounded. The worked
schedules here use denominators dividing 1000 and supports no later than .56.
The bytes below are representation lower bounds, never RSS measurements.

For a single advance from zero to .36 with no extra query split, the eight
phase boundaries force eight segments before d and seven afterward. The
remaining packets are two of dimension n+1, seven of dimension n, and seven of
dimension 2n+1: sixteen in total. Thus, including physical state,
`F=37n²+180n+113`, and `A=5+16×3=53`.

| N/n | F, minimal sixteen-packet final | Hex contents lower bound 11F−53 | F, planned twenty-two-packet warm final | Hex contents lower bound 11F−71 |
|---:|---:|---:|---:|---:|
| 128/127 | 619,746 | 6,817,153 B | 870,084 | 9,570,853 B |
| 256/255 | 2,451,938 | 26,971,265 B | 3,444,164 | 37,885,733 B |
| 512/511 | 9,753,570 | 107,289,217 B | 13,704,132 | 150,745,381 B |

All three fail the existing 900,000-byte snapshot cap even in the minimal
sixteen-packet case. Normal values, signed strings and metadata only increase
these numbers. The current encoder also creates Python string lists before
encoding JSON. `STATIC_COST.json` records a separate interpreter-specific
estimate using the measured small ASCII-string object size and pointer size.
That estimate assumes independent string allocation and is not a portable
peak-RSS certificate. Its first internal attempt used correct computed bytes
but a wrong hardcoded prose object size; all four originals are retained under
`originals/attempt001`, and attempt002 fixes that prose and records measured
size fields without changing the formulas or counts.

## Fixed warm/coarse/cold event denominator

The proposed warm times are `0,.001,.02,.16,.2,.201,.28,.36`; coarse times are
`0,.2,.36`; cold times are the restored `.201` input, `.28` and `.36`. Cold
starts from the complete warm .201 packet object; it does not repeat an
initial trajectory. Each mode must retain its complete raw capsules and
active/upper/M/H/A/R/Z vectors. There are fourteen readouts/capsules and three
direct warm/cold byte pairs per grid.

Warm adds `.001/.02/.16` to the eight pre-d phase intervals, producing eleven
segments before d. Shifted release boundaries and the additional .28 query
produce ten afterward. At .36 the first-hit packet ending at .36 expires;
two old first-hit packets remain. Ten new first-hit and ten second-hit packets
remain, so the final packet count is twenty-two and
`F=52n²+246n+134`, `A=71`.

| Mode | Readouts | Packet counts at readouts | Segments | Advance exponential calls | Observation exponential calls | Total structural calls |
|---|---:|---|---:|---:|---:|---:|
| Warm | 8 | 8, 9, 10, 11, 11, 12, 18, 22 | 21 | 42 | 202 | 244 |
| Coarse | 3 | 8, 8, 16 | 15 | 30 | 64 | 94 |
| Cold from warm .201 | 3 | 12, 18, 22 | 9 | 18 | 104 | 122 |

These are source-level call counts under the stated graph, not executed
exponentials or timing predictions. Every advance segment calls two
exponentials; every readout calls two for every retained continuous packet.
The complete three-grid roster would require 1,380 such calls and 135
segments. The old resume-only per-ledger cap100 and global600/120 budget do
not cover this roster. A future candidate must freeze new bounded budgets;
this review does not silently raise any cap.

Each complete readout contains `C(2n+16)=10n+80` scalars. Count every signed
channel and both generations, including structurally zero or rare values.

| N/n | Scalars/readout | Fourteen observed readouts | Eight unique reference readouts |
|---:|---:|---:|---:|
| 128/127 | 1,350 | 18,900 | 10,800 |
| 256/255 | 2,630 | 36,820 | 21,040 |
| 512/511 | 5,190 | 72,660 | 41,520 |
| Planned total | — | 128,380 | 73,360 |

Eight unique reference times are an intended denominator, not references
evaluated by this review. Relative eligibility remains `abs(reference)>=1e-12`
with null below the floor; all absolute values remain in the denominator.
There is no epsilon packet removal. The N256 missing input blocks claiming
the planned three-grid denominator as completed.

## Existing fail-closed points and minimum next interface

The unchanged Physics constructor first rejects n outside {1,2}. Packet
alpha/mass and physical state are fixed to three channels. `advance` rejects
source+active dimension greater than64; `FluxPacket` rejects dimension
greater than64; the exponential ledger separately rejects augmented dimension
greater than128. The loader rejects any array axis greater than128: n127's
active axis fits, but its second-hit packet does not; n255/n511 active axes
already fail. The raw snapshot cap is900000 B. `MAX_SEGMENTS=128` is an unused
module constant: the actual advance guard is `ledger.segments>20`, so the
proposed warm schedule's twenty-one segments would fail even after spatial
and channel caps were changed. The packet cap128 is not exceeded by the
twenty-two-packet worked example, but further query refinement increases the
number of exact support pieces.

For S event segments, the source appends at most one packet before d and two
after d. Expiry and atom consumption can only lower the count:
`P(t)<=P0+S_pre+2S_post`. This is a count bound, not a bounded-lifetime guarantee
for arbitrary timelines: ledger replacement can reset invocation counters,
while support partition count remains real state. No support coalescing or
numeric-zero pruning is permitted without a separate equivalence proof.

A complete cold object requires all active generations, upper origins,
cumulative M/H/A, every packet's exact support/target/origin/alpha/generator/
selector, and an immutable binding to Q/lower/upper/reset/q/d and source
operator/schema. The present state stores a physics identity, not the full
physics payload; the externally supplied physics and source artifacts remain
part of the recovery dependency denominator. R/Z totals cannot replace the
pending law. Three byte comparisons per grid must compare the independent
cold files directly, including the restored .201 input. Full vector checks
also require all coarse spatial coordinates, not renewal totals alone.

The next implementation needs a new operator/schema identity with generic n
and C, explicit source/input guards, the missing N256 input, and an honest
budget. Sharing immutable generator recipes or sparse structure could remove
duplicated dense packet matrices; a sparse exponential action could avoid
forming each dense exponential. Either change needs its own closure,
positivity, signed-content, complete-restore and error checks. It must not
mutate the frozen finite prototype or turn this static estimate into a
large-grid qualification. Continuum error, arbitrary timelines, full network,
training, gradients and production checkpoint adoption remain open.

Overall: HOLD_NO_GO / all_closed=false. This artifact performs no large-grid
numerical execution and supplies no dynamic-admission evidence.
