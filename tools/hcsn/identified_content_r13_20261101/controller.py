"""R12 finite-horizon model with one declared tie rule at every Bellman node."""

import importlib.util

import numpy as np

from contract import PROTOCOL, R12


def load_source(name, source):
    spec = importlib.util.spec_from_file_location(name, source)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


TIES = load_source('hcsn_r13_stable_ties', R12/'tie_resolution/candidate.py')
CORE = load_source('hcsn_r13_controller', R12/'control/controller.py')


def resolve_action(qvalues):
    return TIES.resolve_action(qvalues, PROTOCOL['tie_tolerance'])


def _result(qvalues):
    action = resolve_action(qvalues)
    return CORE.PlanResult(action, qvalues[np.arange(len(action)), action], qvalues)


# Patch only this independently loaded module, never the R12 source or module.
# Continuation values now reflect the actions this same policy really executes.
CORE._result = _result
plan, plan_mc = CORE.plan, CORE.plan_mc
