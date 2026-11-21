"""Unexecuted source for a future N256 dense-compatible action boundary."""

EXECUTION_ALLOWED = False
BOUNDARY_COORDINATES = 68105
EXTENDED_GENERATOR_SHAPE = (257, 257)
INITIAL_SHAPE = (5, 257)
SELECTOR_SHAPES = ((257, 1), (257, 2))
DURATION_NUMERATOR = 1
DURATION_DENOMINATOR = 1000
DISCOUNT_HEX = ("0x0.0p+0", "0x1.3333333333333p-3")
AUGMENTED_DIMENSIONS = (258, 259)
ACTION_ORDER = ("undiscounted_hit", "discounted_hit_and_occupation")


def canonical_csr_to_dense(matrix, expected_shape, np):
    """Future boundary materialization; not called by this source-only stage."""
    if tuple(matrix.shape) != tuple(expected_shape):
        raise ValueError("CSR boundary shape")
    if str(matrix.dtype) != "float64":
        raise ValueError("CSR boundary dtype")
    if not matrix.has_canonical_format or not matrix.has_sorted_indices:
        raise ValueError("CSR boundary must be canonical and sorted")
    dense = matrix.toarray(order="C")
    if not dense.flags.c_contiguous or str(dense.dtype) != "float64":
        raise ValueError("dense boundary layout")
    if not np.isfinite(dense).all():
        raise ValueError("dense boundary finite values")
    return dense


def dense_compatible_stream_action(generator, initial, selectors, duration, discount, np, expm):
    outputs = selectors.shape[1]
    dimension = generator.shape[0]
    augmented = np.zeros((dimension + outputs, dimension + outputs), dtype="float64")
    augmented[:dimension, :dimension] = generator - discount * np.eye(dimension)
    augmented[:dimension, dimension:] = selectors
    seed = np.concatenate(
        (initial, np.zeros((initial.shape[0], outputs), dtype="float64")), axis=1
    )
    evolved = (expm(augmented.T * float(duration)) @ seed.T).T
    return evolved[:, :dimension], evolved[:, dimension:]
