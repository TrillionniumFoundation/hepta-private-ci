"""Execution08 constructor adaptation for the explicitly registered RAW capacity.

The execution06 backpressure implementation remains literal. Its transactional
methods, physical reserve, C evidence cap, memory inequalities and bounded waits
are inherited unchanged. Only its constructor's 2 GiB identity assertion needs
the separately registered execution08 6 GiB identity. No failed write is retried.
"""

from contextlib import contextmanager
from copy import deepcopy
import importlib
from pathlib import Path

from . import capacity_amendment as amendment
from . import common as c

BACKPRESSURE = importlib.import_module(
    "operational.parameter_field_recovery06.resource_backpressure"
)
ORIGINAL_PRESSURE_BUDGET = BACKPRESSURE.BackpressureBudget
RELATIVE = "operational/parameter_field_recovery08/capacity_backpressure.py"


def registered_budget_type(config):
    pin = config["descriptors"]["amendment"]
    registered = amendment.load_registration(pin["path"], pin["sha256"])
    c.need(
        Path(__file__).resolve() == c.SOURCE / RELATIVE
        and c.descriptor(c.SOURCE / RELATIVE)["sha256"]
        == config["source_files"][RELATIVE]
        and BACKPRESSURE.BackpressureBudget is ORIGINAL_PRESSURE_BUDGET,
        "Execution08 capacity constructor source or original alias differs",
    )
    # The captured literal registration is an immutable comparison target. It is
    # validated again against the committed profile on every construction.
    expected = deepcopy(registered)

    class RegisteredCapacityBudget(ORIGINAL_PRESSURE_BUDGET):
        def __init__(self, root, registration, policy):
            current = amendment.load_registration(pin["path"], pin["sha256"])
            c.need(
                current == expected == registration,
                "Budget requires the exact committed execution08 registration",
            )
            # Invoke only the original resource constructor; the skipped method
            # contains precisely the old identity assertions repeated below.
            BACKPRESSURE.ORIGINAL_BUDGET.__init__(self, root, registration)
            c.need(
                self.root == policy.root
                and (self.cap, self.reserve, self.c_cap, self.margin)
                == (
                    amendment.RAW_CAP,
                    256 * BACKPRESSURE.MiB,
                    350 * BACKPRESSURE.MiB,
                    BACKPRESSURE.GiB,
                )
                and registration["concurrency"]["max_workers"] == 2
                and registration["concurrency"]["worker_reservation_bytes"]
                == 768 * BACKPRESSURE.MiB,
                "Registered execution08 roots or unchanged resource limits differ",
            )
            self.policy = policy

    return RegisteredCapacityBudget


@contextmanager
def installed(config, policy, *, allow_test_policy=False):
    """Install the one constructor alias within the original scoped adapter."""
    budget = registered_budget_type(config)
    # This global selects the class used by the original installer, training
    # slots, guarded writes and literal restore. All those functions stay intact.
    BACKPRESSURE.BackpressureBudget = budget
    try:
        with BACKPRESSURE.installed(
            policy, allow_test_policy=allow_test_policy
        ) as installation:
            yield {
                **installation,
                "execution_episode": c.EPISODE,
                "capacity_constructor": c.descriptor(c.SOURCE / RELATIVE),
                "original_backpressure_implementation": c.descriptor(
                    Path(BACKPRESSURE.__file__).resolve()
                ),
                "only_constructor_capacity_identity_changed": True,
            }
    finally:
        BACKPRESSURE.BackpressureBudget = ORIGINAL_PRESSURE_BUDGET
