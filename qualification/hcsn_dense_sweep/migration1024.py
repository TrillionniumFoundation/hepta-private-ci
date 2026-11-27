"""New candidate's cap extension; the frozen <=512 MigrationBasis is unchanged."""

from dataclasses import dataclass

from qualification.hcsn_initial_law.migration import MigrationBasis, exact


@dataclass(frozen=True)
class MigrationBasis1024(MigrationBasis):
    def __post_init__(self):
        for name in ("original_endpoint", "tail_rate", "delay", "target_endpoint"):
            object.__setattr__(self, name, exact(getattr(self, name)))
        if (type(self.active_cells) is not int or not 1 <= self.active_cells <= 256
                or type(self.phase_cells) is not int or not 1 <= self.phase_cells <= 128
                or type(self.intervals) is not int or not 4 <= self.intervals <= 1024
                or not 0 < self.original_endpoint <= self.target_endpoint <= 8
                or self.tail_rate <= 0 or not 0 < self.delay <= 2):
            raise ValueError("invalid independent 1024-cap source/target basis")
        nodes = (tuple(self.target_endpoint * j / self.intervals
                       for j in range(self.intervals + 1)) if self.actual_nodes is None
                 else tuple(map(exact, self.actual_nodes)))
        if (len(nodes) != self.intervals + 1 or nodes[0] != 0
                or nodes[-1] != self.target_endpoint
                or any(b <= a for a, b in zip(nodes, nodes[1:]))):
            raise ValueError("strict actual nodes must span zero to target endpoint")
        object.__setattr__(self, "actual_nodes", nodes)
