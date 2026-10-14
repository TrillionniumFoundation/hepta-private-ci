"""Q24 static Gate folding regression, exact integer arithmetic only."""
import random
import pytest

from neuron_shared_encoder.q24_fold_ablation import (
    Q24, MAX_ABS_Q24, round_q48_to_q24, static_gate_vs_folded_q24,
)


def test_rounding_matches_rust_ties_to_even_for_both_signs():
    assert [round_q48_to_q24(raw) for raw in
            (Q24//2, 3*Q24//2, -Q24//2, -3*Q24//2)] == [0, 2, 0, -2]
    with pytest.raises(ValueError, match='range'):
        round_q48_to_q24(9*Q24*Q24)
    with pytest.raises(OverflowError):
        round_q48_to_q24(1 << 127)


def test_static_gate_one_folds_bit_identically():
    example = static_gate_vs_folded_q24(
        [Q24//2, -Q24//3, Q24//9], [Q24, Q24, Q24],
        [[Q24//2, -Q24//4, Q24//7], [Q24//4, 0, -Q24//8]],
        [Q24//4, -Q24//4],
    )
    assert example['bit_identical'] is True
    assert example['max_abs_error_q24_units'] == 0
    assert example['production_admission'] == 'BLOCKED'


def test_real_algebraic_fold_can_differ_by_one_q24_lsb():
    # Documented deterministic witness, not statistical proof.
    result = static_gate_vs_folded_q24(
        [9843101], [9650900], [[-8831556]], [0],
    )
    assert result['original_q24'] == [-2980555]
    assert result['folded_q24'] == [-2980556]
    assert result['max_abs_error_q24_units'] == 1
    assert result['bit_identical'] is False


def test_bounded_random_integer_regression_no_unbounded_numeric_claim():
    rng = random.Random(31014)
    differences = []
    for _ in range(128):
        xs = [rng.randrange(-Q24, Q24) for _ in range(6)]
        gs = [rng.randrange(-Q24, Q24) for _ in range(6)]
        w = [[rng.randrange(-Q24, Q24) for _ in range(6)] for _ in range(2)]
        row = static_gate_vs_folded_q24(xs, gs, w, [0, 0])
        assert len(row['original_q24']) == 2
        assert row['max_abs_error_real'] == row['max_abs_error_q24_units'] / Q24
        differences.append(row['max_abs_error_q24_units'])
    assert max(differences) > 0
    # This bound is only on this fixed sample, not a global equivalence bound.
    assert max(differences) < 16


@pytest.mark.parametrize('values,gate,weights,biases', [
    ([1, 2], [1], [[1, 1]], [0]),
    ([1], [1], [[1, 2]], [0]),
    ([1], [1], [[1]], []),
    ([1], [1], [[1]], [0, 0]),
    ([1.5], [1], [[1]], [0]),
    ([True], [1], [[1]], [0]),
    ([MAX_ABS_Q24+1], [1], [[1]], [0]),
])
def test_invalid_dimensions_types_and_bounds_fail_closed(values,gate,weights,biases):
    with pytest.raises(ValueError):
        static_gate_vs_folded_q24(values, gate, weights, biases)
