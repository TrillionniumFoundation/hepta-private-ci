# Training-before-data resolution risk probe

This independent, numerical-only design check is authorized before any task
dataset is read or any task fit is started. It does not change the qualified
FV v1 eighteen-file source, its earlier protocol, or its evidence. The source
identity includes the frozen FV source, fixed_renewal.py and this probe.

The exact pilot parameters are mu=-.1, sigma=.3, q=.15, reset margin=.25,
physical refractory=.1, finite endpoint L=2, exponential tail rate=1 and
initial point x=.35. Two schedules each have 64 steps and total physical time
exactly 4: (.025,.05,.075,.1) repeated sixteen times, and .0625 repeated
sixty-four times. No observations or conditioning updates occur.

The three prospective configurations are N16/P8, N64/P16 and N128/P32.
Each uses the already qualified fixed-operator implementation with its
unchanged order-doubling and mass rejection guards. FP64 and FP32 executions
are compared. FP64 matrices are explicitly constructed before materialization.
Grid/duration and state-projection approximations remain part of the model.

The direct P4 reference does no repeated grid projection. It sums the initial
killed law and the finite positive-delay renewal release laws. The release
identity is first checked at T=.08,.1,.32,.7 against the original adaptive
time-convolution FP64 reference, including phase masses and all reward
channels. Every crosscheck requires state L1 and scalar absolute errors <=2e-8.
Reference failure prevents any recommendation. Occupation uses positive
survivor/release integrals, not a subtractive near-zero q formula.

All configurations are aggregated to the common sixteen active bins, explicit
tail and eight refractory bins without normalization. A configuration is
eligible only if BOTH schedules and BOTH execution dtypes achieve common-bin
state L1 <=.02 and cumulative undiscounted-hit relative error <=.03. The direct
hit expectation is nonzero in this fixture. Occupation and discounted hits
are also reported; no post-hoc gate is added to those diagnostics. The chosen
configuration is the smallest of the predeclared configurations that passes.
If none passes, this probe returns no recommendation rather than changing the
thresholds or consuming task results to select another design.

The same-T difference between the two schedules is explicitly reported,
because QPR remapping creates a schedule-dependent semigroup defect. Passing
these fixture gates is not a uniform approximation theorem, a guarantee for
arbitrary observation-conditioned distributions, or evidence of task benefit.

All attempted configurations, rejection exceptions, source hashes and elapsed
construction/execution costs are retained. The cloud stage is bounded at
300 seconds, reuses the already owned Colab lease and has zero task-data reads
and zero task training updates. Physical full-machine energy remains unknown.
