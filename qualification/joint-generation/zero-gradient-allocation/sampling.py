"""Command-only allocation for a fixed-decoder semantic-transport objective.

Fully specified commands have parameter-independent final serving loss. Keeping
only other rows and multiplying their mean gradient by their population fraction
preserves the original mean gradient mathematically, before floating roundoff,
clipping or Adam. This claim does NOT extend to the optimizer update or to a
trainable decoder. No targets, outcomes, model scores or best-seed choices enter
the allocation rule.
"""
from dataclasses import dataclass
from control import Command


@dataclass(frozen=True)
class Allocation:
    population: int
    indices: tuple

    def __post_init__(self):
        if (type(self.population) is not int or self.population<1
                or type(self.indices) is not tuple or not self.indices
                or any(type(i) is not int or not 0<=i<self.population for i in self.indices)
                or tuple(sorted(set(self.indices)))!=self.indices):
            raise ValueError('nonempty unique canonical row allocation required')

    @property
    def gradient_weight(self):
        return len(self.indices)/self.population


def allocate(commands):
    """Retain at least one legacy keep word; all-keep rows remain eligible."""
    if type(commands) not in (list,tuple) or not commands or any(type(c) is not Command for c in commands):
        raise ValueError('fixed explicit command inventory required')
    indices=tuple(i for i,c in enumerate(commands) if any(word==0 for word in c.values))
    return Allocation(len(commands),indices)
