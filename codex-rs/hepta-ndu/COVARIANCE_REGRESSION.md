# Native shadow covariance regression V1

`admit_covariance_profile` validates an immutable numerical profile and binds its
units, coordinate order, dimensions, covariance convention and bounds into a
digest. This local admission does not approve an artifact, register a production
protocol or change any selected coefficient. Existing deterministic Q32 APIs are
unchanged. The new structures are native Rust f64 values with their own V1 digest
namespace; they are not a reinterpretation of `NduCoefficientManifestV1` bytes.

`estimate_conditional_moments` processes 2–512 samples from one externally defined
pre-boundary conditioning stratum and one duration. It centers both increments
and utility using online updates, with population divisor n. Matching conditioning
digests enforce grouping; source authentication, feature timing, fold isolation
and statistical identification remain the caller's responsibility. Samples and
matrices must be finite and remain within the admitted bounds. Driver dimension
is 1–32 and utility dimension is 1–8.

`solve_backward_regression` solves `Z Sigma = B` using scaled Cholesky triangular
solves. Increment profiles store Sigma directly. Rate-per-second profiles store
`Q = Sigma / dt` and solve `Z Q = B / dt`; B always has increment units. Durations
are integer microseconds in [1,000, 3,600,000,000], explicitly converted to seconds.
The eigenvalue floor always refers to increment covariance. There is no implicit
identity covariance, regularization, matrix inverse, pseudoinverse or clipping.

For symmetric positive definite matrices, column solves give the inverse 1-norm;
`||Sigma||1 * ||Sigma^-1||1` conservatively bounds the spectral condition number,
and `1 / ||Sigma^-1||1` bounds the smallest eigenvalue from below in exact
arithmetic. Native f64 values are numerical diagnostics, not certified interval
bounds. Conservative admission can reject a covariance whose spectral condition
number alone would pass. The condition ceiling cannot exceed 1e6. Every utility
row also checks its coefficient bound and normalized backward residual against
the supplied covariance, including any tolerated roundoff asymmetry.

Errors return no candidate. Receipts bind the actual moments, profile, duration,
source/conditioning digests, solution and diagnostics, and always use `DENY_ALL`.
No fallback artifact is selected here; an owner integration must consult current
revocations and its compatible deterministic predecessor.

The native tests cover scaled and correlated analytic oracles, nonzero sample
means, rate/duration conversion, identity covariance, singular/indefinite and
poorly conditioned matrices, covariance collapse, invalid samples/profiles,
zero sensitivity, deterministic replay and the full 32-driver/8-utility envelope.

Remaining gates include production coefficient-profile registration and consumer
integration, original/whitened coordinate conversion, Q24 conversion/error
receipts, independent mathematical review, conditional identification,
well-posedness/stochastic FBSDE qualification and named-host resource/latency
measurements. Algebraic regression tests do not establish those capabilities.
