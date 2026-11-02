# Native finite financial construction

The three inputs are sigma, liquidity and maturity in the unchanged R12 box. Six other financial parameters remain fixed. Rust constructs the static H-X boundary, the 40-state synthetic regenerative row generator, emissions and prior. This removes a supplied Python matrix from this declared profile. It is not a full equity/debt implementation, continuum stopping verification, trainable neural network or production model admission.

For nonnegative u, the normal tail is represented by

\[
\Phi(-u)=\frac{e^{-u^2/2}}{\sqrt{2\pi}}\int_0^\infty e^{-ut-t^2/2}\,dt.
\]

The native implementation truncates at 12 and integrates twelve unit panels using 16-point Gauss-Legendre. Omitted tail is at most Phi(-12); that exact-arithmetic truncation observation is not a uniform quadrature or FP64 roundoff proof. Positive-argument symmetry does not preserve an unrepresentably small positive upper complement, and no such preservation is claimed. The declared relative check directly covers negative tails to -12. There is no floor, clipping or normalization.

With z and s from the financial kernel, define N(y)=Phi(y*s)-exp((z*z-y*y)*s*s/2)*Phi(-z*s). Since N(-z)=0, the divided difference B(y)=N(y)/(z+y) equals the integral of N'(-z+t*(z+y)) over t in [0,1]. Rust always uses this smooth derivative integral, avoiding the removable denominator. The independent 80-digit reference uses the direct quotient instead; the retained Python R11/R12 implementation is a third check. Full arrays, rather than only selected boundary values, are compared.

Primary numerical definitions: [NIST DLMF error functions](https://dlmf.nist.gov/7.2), [Gaussian integral representations](https://dlmf.nist.gov/7.7), and [Gauss-Legendre quadrature](https://dlmf.nist.gov/3.5). The financial expression and finite extension are ported from the exact baseline R11 FullHX and R12 Cell; financial regeneration is an explicitly synthetic extension. Eight corner cases and 64 fresh parameter draws are a finite verification profile, not an all-input proof. Reset interpolation knots, out-of-box parameters and inadmissible boundaries reject.

R19 and all old source bytes remain unchanged. Initial missing-dependency and JSON serialization failures are retained, including complete first-run raw numerical data. No failed scientific threshold is repaired or erased. All global efficacy, full-gradient, continuous-boundary, GPU/energy and production gates retain their original requirements.
