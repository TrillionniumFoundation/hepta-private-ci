"""One zero-model SciPy 1.17 constructor compatibility probe."""

import json

from scipy import sparse


def main():
    values = (0.0, 1.25, 0.0)
    matrix = sparse.csr_matrix([values], dtype="float64").T
    if matrix.shape != (3, 1):
        raise ValueError("list-row transpose shape")
    if matrix.toarray().reshape(-1).tolist() != list(values):
        raise ValueError("list-row transpose values")
    print(json.dumps({
        "schema": "hcsn-n256-scipy17-listrow-compatibility-probe-v1",
        "sparse_constructor_calls": 1,
        "model_calls": 0,
        "expm_actions": 0,
        "optimizer_steps": 0,
        "shape": list(matrix.shape),
        "status": "PASS",
    }, separators=(",", ":"), sort_keys=True))


if __name__ == "__main__":
    main()
