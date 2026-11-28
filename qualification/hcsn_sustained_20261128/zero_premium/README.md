# Coincident discount roots in the published equity cell

In the stationary He–Xiong pricing law, the roots z and zbar coincide when the liquidity premium is zero. Eq. 12 for the boundary and Appendix A7 for equity both include a divided difference whose denominator tends to zero. With the published positive risk-free rate and the remaining Table I parameters, the values and their live-margin derivatives remain finite at zero premium. This case also matters for the baseline with perfectly liquid debt. [Original equations and calibration](https://www.princeton.edu/~wxiong/papers/rollover.pdf)

The fix evaluates the divided difference as the average of its analytic derivative along the interval between roots. A two-point Gauss rule on the short interval gives a fourth-order error in the root separation for a smooth derivative. At coincident roots both points equal the root, so the expression gives the derivative directly. Boundary slopes use the scalar normal density. Equity uses Torch operations so that value and first derivatives with respect to log margin and principal remain on the training graph. The existing direct expression is used outside the near-coincident interval. The liquidity premium is a fixed law coefficient in this module.

The independent test integrates the discounted first-passage equation on the half-line to determine the boundary, then integrates the equity initial-value equation to obtain values and margin derivatives. The principal derivative follows from changing the nominal principal by one unit at fixed log margin, where equity is affine in principal. The panel includes zero premium, 10⁻¹⁶ to 10⁻⁵, both sides of the numerical switch, the original positive premiums, and a two-year contract with different volatility, rates and principal. It also covers ordinary autograd through the absorbed-state extension.

Four unit tests passed on ai395 with one CPU Torch thread. A second sweep used eight premia, two maturities and two principals. Across six log margins per contract the maximum absolute differences were 1.86e−11 for the boundary, 3.42e−10 for equity, 2.34e−9 for its margin gradient and 5.15e−12 for its principal gradient. The original module raised ZeroDivisionError when constructing the zero-premium law. On the default positive-premium contract, checkpoint-matched original and repaired LiteralCell instances gave identical logits, input gradients and all parameter gradients for eight frames. Each reported difference was exactly zero in FP64.

The first remote sweep attempted to import SciPy and exited before testing. The executed target reference uses NumPy Gauss–Legendre quadrature and fourth-order Runge–Kutta integration. A separate local comparison at the four Table I liquidity settings agreed with the adaptive SciPy equity values within 1.02e−11. The recorded execution used Python 3.14.4, NumPy 2.5.2 and PyTorch 2.13.0+rocm10.0.0 on CPU.

To repeat the four regressions, place the test beside the repaired module and run the following command. To repeat the independent sweep in an isolated directory, add the archived original module under the filename original.py alongside he_xiong.py, the unit test and sweep.py. The receipt gives SHA-256 for the original and repaired files.

```sh
python -B -m unittest -v test_he_xiong_zero_premium
python -B sweep.py
```

[Recorded measurements](result.json) · [Complete CPU test output](ai395_cpu.log)
