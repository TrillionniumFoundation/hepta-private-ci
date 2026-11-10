"""Frozen logical Cell population for the experimental seven-lineage owner.

Lineages are engineering responsibilities, not learned competencies. This plan
selects implemented producer families and local update points; it does not admit
HCSN, establish task benefit, or grant native daemon execution authority.
"""

from dataclasses import asdict, dataclass, fields

from .component_types import Budget, CellError, Partition, _hex, _token, digest


LINEAGES = ("PERC", "MEM", "PRED", "CTRL", "VERIFY", "ACT", "LEARN")
SCHEMA = "hepta.cell.population-plan.v1"


@dataclass(frozen=True)
class CellSpec:
    """One logical instance; run-specific state remains with ``Partition``.

    A plastic instance pins the host's objective, update rule and evaluation
    profile before candidate production. ``min_observations`` is an admission
    interval; the state owner must count original committed observations.
    """

    cell_id: str
    lineage: str
    family: str
    kernel: str
    initial_identity: str
    objective: str
    trainable: str = "frozen"
    update_rule: str | None = None
    evaluation_profile: str | None = None
    min_observations: int = 1
    budget: Budget = Budget()
    total_work_units: int = 1000000

    def __post_init__(self):
        for value in (
            self.cell_id,
            self.lineage,
            self.family,
            self.kernel,
            self.objective,
            self.trainable,
        ):
            _token(value)
        _hex(self.initial_identity)
        if self.lineage not in LINEAGES:
            raise CellError("unknown functional lineage")
        routes = {
            "shared_semantic": (
                ("PERC", "MEM", "VERIFY"),
                ("shared_head",),
                ("frozen", "heads"),
            ),
            "stateful_temporal": (
                ("PRED", "CTRL", "ACT"),
                ("gru", "diag_ssm"),
                ("frozen", "kernel_and_heads"),
            ),
            "deterministic": (
                LINEAGES,
                ("retrieval", "rule_verifier", "numerical", "tool_wrapper"),
                ("frozen",),
            ),
        }
        if self.family not in routes:
            raise CellError("unknown implemented Cell family")
        lineages, kernels, parts = routes[self.family]
        if (
            self.lineage not in lineages
            or self.kernel not in kernels
            or self.trainable not in parts
        ):
            raise CellError("lineage, kernel and trainable scope are incompatible")
        if self.plastic:
            _hex(self.update_rule)
            _hex(self.evaluation_profile)
        elif self.update_rule is not None or self.evaluation_profile is not None:
            raise CellError("frozen instances must not declare a local training rule")
        if (
            type(self.min_observations) is not int
            or not 1 <= self.min_observations <= 1000000
        ):
            raise CellError("invalid bounded observation interval")
        if type(self.budget) is not Budget:
            raise CellError("instance budget must be an immutable Budget")
        if (
            type(self.total_work_units) is not int
            or not 1 <= self.total_work_units <= 1000000000000
        ):
            raise CellError("invalid total instance work budget")

    @property
    def plastic(self):
        return self.trainable != "frozen"

    def record(self):
        return asdict(self)

    @classmethod
    def from_record(cls, record):
        if type(record) is not dict or set(record) != {f.name for f in fields(cls)}:
            raise CellError("Cell specification fields differ from the frozen schema")
        budget = record["budget"]
        if type(budget) is not dict or set(budget) != {
            f.name for f in fields(Budget)
        }:
            raise CellError("instance budget fields differ from the frozen schema")
        return cls(**dict(record, budget=Budget(**budget)))


@dataclass(frozen=True)
class PopulationPlan:
    """Seven responsibilities, bounded instances and at most three update points.

    A Cell ID is a logical update point regardless of how many run partitions
    use it. Repeated runs therefore neither expand nor consume the plastic cap.
    State-owner row and work bounds remain separate from this logical cap.
    """

    principal_id: str
    agent_id: str
    cells: tuple[CellSpec, ...]
    max_plastic_cells: int = 2

    def __post_init__(self):
        _token(self.principal_id)
        _token(self.agent_id)
        if (
            type(self.max_plastic_cells) is not int
            or not 0 <= self.max_plastic_cells <= 3
        ):
            raise CellError("initial plasticity cap must be between zero and three")
        if (
            type(self.cells) is not tuple
            or not 7 <= len(self.cells) <= 128
            or any(type(cell) is not CellSpec for cell in self.cells)
        ):
            raise CellError("population requires an immutable tuple of 7..128 instances")
        if len({cell.cell_id for cell in self.cells}) != len(self.cells):
            raise CellError("logical Cell identifiers must be unique")
        if {cell.lineage for cell in self.cells} != set(LINEAGES):
            raise CellError("population must retain all seven functional lineages")
        if sum(cell.plastic for cell in self.cells) > self.max_plastic_cells:
            raise CellError("population exceeds its frozen plasticity cap")
        object.__setattr__(
            self, "cells", tuple(sorted(self.cells, key=lambda cell: cell.cell_id))
        )

    def record(self):
        return dict(
            schema=SCHEMA,
            principal_id=self.principal_id,
            agent_id=self.agent_id,
            cells=[cell.record() for cell in self.cells],
            max_plastic_cells=self.max_plastic_cells,
        )

    @property
    def digest(self):
        return digest(self.record())

    @classmethod
    def from_record(cls, record):
        if type(record) is not dict or set(record) != {
            "schema",
            "principal_id",
            "agent_id",
            "cells",
            "max_plastic_cells",
        }:
            raise CellError("population fields differ from the frozen schema")
        if record["schema"] != SCHEMA or type(record["cells"]) is not list:
            raise CellError("invalid population schema or instance collection")
        if not 7 <= len(record["cells"]) <= 128:
            raise CellError("population instance count is outside its bound")
        return cls(
            record["principal_id"],
            record["agent_id"],
            tuple(CellSpec.from_record(cell) for cell in record["cells"]),
            record["max_plastic_cells"],
        )

    def spec(self, partition):
        if type(partition) is not Partition or (
            partition.principal_id != self.principal_id
            or partition.agent_id != self.agent_id
        ):
            raise CellError("partition belongs to another population owner")
        for cell in self.cells:
            if cell.cell_id == partition.cell_id:
                return cell
        raise CellError("Cell instance is absent from the frozen population")

    @property
    def lineage_counts(self):
        return {
            lineage: sum(cell.lineage == lineage for cell in self.cells)
            for lineage in LINEAGES
        }
