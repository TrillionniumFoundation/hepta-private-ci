# R4 primary forward-Stem weights

Six actual 108-parameter vectors, three Adam and three population-adjoint fits
at the nominal eight-second CPU cap. The array order is MatrixStem.weights,
shape (3,2,3,6), little-endian float64. These are research coefficients, not
admitted native artifacts or a production model switch.

Decode each ASCII file using bytes.fromhex; ASCII whitespace is immaterial.
Require exactly 864 decoded bytes and verify the SHA256 in SHA256.json before
constructing np.frombuffer(raw, dtype='<f8').copy() and calling solve.assign.
Never interpret the hexadecimal digits as decimal floating-point values.
The complete archive contains initial tensors, all 29 saved coefficient arrays,
raw predictions, source hashes and independent reference checks.
