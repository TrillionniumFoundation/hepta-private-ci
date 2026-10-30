"""Versioned cold-process suffix runner; never imports the unsafe V1 loader."""
import argparse

import jax.numpy as jnp

from tools.hcsn.task_flow_20261030.flow import api
from .checkpoint import load_checked, save_v2


def suffix(params, state):
    """Same two known observations/gaps as the frozen flow recovery probe."""
    dtype = params["input"].dtype
    first = jnp.asarray([.3, -.2, .1], dtype=dtype)
    second = jnp.asarray([-.7, .4, .2], dtype=dtype)
    state = api.observe(params, first, api.checked_propagate(state, .17))
    return api.observe(params, second, api.checked_propagate(state, 1.6))


def restore_and_continue(checkpoint, destination, *, precision):
    params, state = load_checked(checkpoint, expected_precision=precision)
    continued = suffix(params, state)
    save_v2(destination, params, continued, precision=precision)
    return continued


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--checkpoint", required=True)
    parser.add_argument("--destination", required=True)
    parser.add_argument("--precision", choices=("float32", "float64"), required=True)
    args = parser.parse_args()
    restore_and_continue(args.checkpoint, args.destination, precision=args.precision)


if __name__ == "__main__":
    main()
