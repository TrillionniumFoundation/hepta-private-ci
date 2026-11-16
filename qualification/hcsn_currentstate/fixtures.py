"""Frozen synthetic finite controls, distinct from the retained large profiles."""
from fractions import Fraction as F
import numpy as np

from .packets import Physics, State, FluxPacket, AtomPacket


FINE = tuple(F(x) for x in ("0", ".001", ".025", ".0625", ".13", ".2", ".201", ".28", ".36"))
COARSE = (F(0), F(1, 5), F(9, 25))
RESUME = F(201, 1000)


def fixture(name):
    if name == "mixed":
        physics = Physics([[-3., 1.], [3., -3.5]], [2., 0.], [0., .5], [.25, .75])
        active = np.zeros((3, 2, 2))
        active[:, 0] = [[1/8, 1/4], [1/16, -1/8], [-3/32, 1/16]]
    elif name == "rare":
        physics = Physics([[-(.5+2**-14)]], [2**-14], [.5], [1.])
        active = np.zeros((3, 2, 1))
        active[:, 0, 0] = [3/8, 1/16, -3/32]
    else:
        raise ValueError("unknown frozen fixture")
    upper = np.zeros((3, 3)); upper[:, 0] = [1/8, -1/32, 1/16]
    width = F(1, 40)
    uniform_mass = np.array([3/8, 1/8, -1/16])
    pending = (FluxPacket(F(0), width, (uniform_mass/float(width))[:, None],
                          [[0.]], [1.], 1, 0),
               AtomPacket(F(1, 16), [1/8, 1/16, -1/8], 1, 0))
    return physics, State(physics.identity, F(0), active, upper,
                          np.zeros((3, 2)), np.zeros((3, 2)), np.zeros((3, 3)), pending)
