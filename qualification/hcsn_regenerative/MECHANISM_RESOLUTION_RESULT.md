# Pretraining resolution audit: select N64/P16 and retain the N16/P8 failure

## Decision

Use **64 active cells, one explicit tail coefficient and 16 refractory cells**:
81 probability coefficients in total. This was the smallest of the three
predeclared configurations that met both numerical criteria for both schedules
and both execution dtypes. The parent accepted this choice before formal task
fits. All arms, operator shapes, model dimensions, parameter checks, memory
reports and the plan must use this capacity consistently. With the existing
observer/gate/readout architecture the learned parameter count is
`136 + 34 × 81 = 2,890`. The planned 160 fits × 400 updates remain unchanged;
the larger computation and state storage must still be included in measured costs.

The original 16/8 configuration failed substantially: its worst common-bin
state L1 error was **0.20530385943**, and its worst cumulative-hit relative
error was **17.66881111%**. These failures remain in the immutable receipt.
They cannot be explained by FP32 rounding: FP64 produces the same large error.
The successful short-horizon FV qualification did not establish this long
trajectory's accuracy.

| Active / phase cells | Probability coefficients | Worst state L1 | Worst hit relative error | Prospective outcome |
|---|---:|---:|---:|---|
| 16 / 8 | 25 | 0.20530385943 | 17.66881111% | FAIL |
| 64 / 16 | 81 | 0.01584776136 | 1.18659876% | pass; smallest eligible |
| 128 / 32 | 161 | 0.00421835768 | 0.29844568% | pass |

## Predeclared question and implementation

The probe used exactly mu=-.1, sigma=.3, discount=.15, initial log distance
.35, reset margin .25, physical refractory duration .1, finite endpoint 2
and exponential tail rate 1. It propagated the supplied distribution through
64 calls, without observations or likelihood conditioning.

Two schedules both end at exactly four physical seconds:

- `unequal`: `.025, .05, .075, .1` repeated sixteen times;
- `equal`: `.0625` repeated sixty-four times.

The gate, frozen before cloud execution, required common-bin state L1 <= .02
and cumulative undiscounted-hit relative error <= .03. A configuration had
to satisfy both gates on both schedules in FP64 and FP32. Comparisons aggregate
to the same sixteen active intervals, explicit upper tail, and eight refractory
intervals, without normalization. Occupation and discounted-hit errors were
recorded as diagnostics and were not given post-hoc acceptance thresholds.

This was a numerical design choice. The process read zero task datasets,
executed zero task optimizer updates, and did not use a task outcome to tune
resolution. The original FV eighteen-file source remained unchanged.

## Independent direct-process reference

The reference evaluates P_T directly from the initial killed law plus the
finite positive-delay renewal sum. Its release contribution uses the independently
derived integrated release-convolution identity. It does not repeatedly apply
QPR or use a tensor transition matrix. Refractory mass uses first-hit CDF
intervals; discounted occupation uses positive survival/release integrals.

Before applying this reference at T=4, the same implementation was checked
against the original adaptive time-convolution scalar reference at
T=.08, .1, .32 and .7. All four checks passed the predeclared 2e-8 absolute
threshold for state L1 and all three scalar reward channels. The largest
observed state difference was 5.989295881484146e-15; the largest occupation
difference was 5.551115123125783e-17. Undiscounted and discounted hit sums
agreed at the displayed floating-point precision in all four cases.

At T=4, the direct reference returned:

- expected hits: 1.8940695199519977;
- expected discounted hits: 1.411552811483848;
- discounted active occupation: 2.869065801487954;
- total mass residual: 0;
- finite renewal terms considered: 41;
- occupation quadrature error estimate: 2.584067170929906e-12.

The finite delay implies no omitted renewal terms beyond the horizon. This is
separate from floating-point error: the reference recorded 100 underflowed
interval evaluations and retained that diagnostic. Its conservation check and
crosschecks are numerical evidence, not a global error certificate.

## All twelve measured cases

Every predeclared configuration was measured; no failed configuration or
unfavourable schedule was removed. `pass` in this table refers only to the
state and cumulative-hit gates. The process exit status `complete` means the
measurement completed, not that every configuration passed.

| Active / phase | Dtype | Schedule | State L1 | Hit relative error | Discounted-hit absolute error | Occupation absolute error | Gate |
|---|---|---|---:|---:|---:|---:|---|
| 16/8 | FP64 | unequal | 0.19960921429 | 17.61262199% | 0.27456029134 | 0.02891778220 | FAIL |
| 16/8 | FP64 | equal | 0.20530385943 | 17.66881111% | 0.27263359343 | 0.02854516152 | FAIL |
| 16/8 | FP32 | unequal | 0.19960930520 | 17.61259411% | 0.27455990752 | 0.02891821242 | FAIL |
| 16/8 | FP32 | equal | 0.20530380523 | 17.66876784% | 0.27263303515 | 0.02854671219 | FAIL |
| 64/16 | FP64 | unequal | 0.01566257220 | 1.17237326% | 0.01829226292 | 0.00194363148 | pass |
| 64/16 | FP64 | equal | 0.01584776136 | 1.18659876% | 0.01834639741 | 0.00193448806 | pass |
| 64/16 | FP32 | unequal | 0.01566281525 | 1.17233872% | 0.01829182660 | 0.00194480221 | pass |
| 64/16 | FP32 | equal | 0.01584767351 | 1.18659091% | 0.01834631051 | 0.00193462056 | pass |
| 128/32 | FP64 | unequal | 0.00415943634 | 0.29489009% | 0.00460118219 | 0.00047690932 | pass |
| 128/32 | FP64 | equal | 0.00421812156 | 0.29844568% | 0.00461429284 | 0.00047446259 | pass |
| 128/32 | FP32 | unequal | 0.00415958938 | 0.29486121% | 0.00460083287 | 0.00047783151 | pass |
| 128/32 | FP32 | equal | 0.00421835768 | 0.29839990% | 0.00461361355 | 0.00047548994 | pass |

The worst observed final mass residual over the FP32 trajectories was
1.3113021850585938e-6 in absolute value. No transition normalization repaired
it. All FP64 mass residuals were below 4e-15. Close FP32 and FP64 errors make
projection, rather than execution precision, the main limitation in this fixture.

## Same-time schedule discrepancy

For the exact time-homogeneous process, both unconditioned schedules represent
P_4. Repeated QPR remapping depends on the observation partition. The measured
same-time differences therefore expose numerical composition error; they are
not evidence that one physical schedule changes the unconditioned P_4 law.

| Active / phase | Dtype | State L1 between schedules | Hit-count difference | Discounted-hit difference | Occupation difference |
|---|---|---:|---:|---:|---:|
| 16/8 | FP64 | 0.02399097500 | 0.00106426103 | 0.00192669791 | 0.00037262068 |
| 16/8 | FP32 | 0.02399046044 | 0.00106396951 | 0.00192687237 | 0.00037150023 |
| 64/16 | FP64 | 0.00188702478 | 0.00026944079 | 0.00005413449 | 0.00000914343 |
| 64/16 | FP32 | 0.00188750011 | 0.00026994627 | 0.00005448391 | 0.00001018164 |
| 128/32 | FP64 | 0.00049336969 | 0.00006734526 | 0.00001311065 | 0.00000244673 |
| 128/32 | FP32 | 0.00049338338 | 0.00006702523 | 0.00001278068 | 0.00000234158 |

At the selected 64/16 resolution, the FP32 schedule discrepancy is
0.00188750011148 in state L1. It decreases to 0.00049338338431 at 128/32.
The remaining discrepancy must be disclosed when interpreting time-aware
versus uniform-tick mechanism comparisons.

## Scope of the decision

The result qualifies a resolution choice for this unconditioned base process,
two fixed 64-step schedules, the specified initial point and the specified
numerical gates. It does not certify arbitrary schedules, longer episodes,
all generator parameters, all conditional-boundary cohorts, or arbitrary
observation-conditioned densities. In particular, learned likelihood updates
can emphasize near-boundary cells differently from this unconditioned fixture.
The conditional-boundary, no-reset, zero-refractory and ordinary-core arms keep
their own declared laws and bases. Matching 81 coefficients is not a proof
that their continuum approximation errors are identical.

The exact kernels within each call use physical durations and the declared
refractory law. Reprojection between calls still approximates the continuous
remaining-time distribution. The full QPR trajectory is therefore an explicitly
reported numerical approximation, not an exact continuum semigroup.

The separate mechanism graph qualification checks a three-step observer with
independent NumPy arithmetic and selected finite-difference derivatives on
represented FP32 coefficients. It must not be cited as independent verification
of the underlying physical kernels, all 2,890 parameter derivatives, 64-step
gradients, production checkpoint recovery, or external task benefit.

## Execution, identity and costs

The bounded numerical stage ran on the already owned Colab environment using
CPU Torch for both FP64 and FP32. No additional GPU was provisioned. The limit
was 300 seconds; the stage completed within it. The recorded clocks overlap
and must not be added:

- cloud execution wall: 19.991919994 seconds;
- probe internal wall: 15.576382373 seconds;
- probe process CPU: 15.468969408 seconds.

Full-machine physical energy is unknown. The separately recorded GPU device
counter interval is 184.537 joules, including idle and unattributed runtime
activity during this CPU numerical stage. It is not model-exclusive energy
and is not a replacement for physical full-machine measurement.

The runtime manifest's twenty-two-file identity includes both hashes and byte
sizes. The receipt's internal source-map digest hashes the path-to-SHA map;
the two digests have different encodings and bind the same verified files.

- runtime freeze identity: `eae23c9ff3a15f326c63e8ff14bf71bdaa023731a5fe37414f9076b79b56746e`;
- receipt source-map digest: `8c83d4490003d3a5fcee1ff8de87dd4872f1e85a384907f03a2a558ec3886a2e`;
- parent FV eighteen-file identity: `b454cfe9f00a412b8201822142d9a8dec043de71cfcefb7efbae2ce133081ce3`;
- raw `resolution-probe.json` SHA256: `a5a286d46f15964c52413ebe594936fba6267c67de1fe5beafe526ebd06c0588`;
- immutable artifact ZIP SHA256: `4e6ad172a60199f0698855ef0c818c6a38edbce432b60a5780ea0fd0dbcc93cb`.

The full receipt retains all twelve terminal vectors, all 768 step trace
entries, construction diagnostics, four reference crosschecks, source hashes
and all failed gates. Original campaign completion credit remains zero.
