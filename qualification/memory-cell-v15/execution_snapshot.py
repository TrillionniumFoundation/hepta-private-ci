"""Freeze trusted host callbacks before binding a durable evaluation request.

The byte identity includes callback state and defining modules, not all imported
libraries or external services. Their identity/isolation remains the trusted
loader's responsibility. Never accept client pickle data through this interface.
Serialization and trusted reconstruction can execute setup before reservation;
the durable boundary covers predictor/executor dispatch, not arbitrary setup.
Setup, snapshotting and ledger IO remain part of full operating cost.
"""

import hashlib
import inspect

import cloudpickle

from isolated_runner import MAX_INPUT, SERIALIZATION_LOCK


def freeze_execution(*callbacks):
    modules = {inspect.getmodule(callback) or inspect.getmodule(type(callback)) for callback in callbacks}
    modules = {module for module in modules if module is not None and module.__name__ != 'builtins'}
    with SERIALIZATION_LOCK:
        prior = cloudpickle.list_registry_pickle_by_value()
        added = [module for module in modules if module.__name__ not in prior]
        try:
            for module in added:
                cloudpickle.register_pickle_by_value(module)
            snapshot = cloudpickle.dumps(callbacks, protocol=5)
            identities = tuple(hashlib.sha256(cloudpickle.dumps(callback, protocol=5)).hexdigest()
                               for callback in callbacks)
        finally:
            for module in added:
                cloudpickle.unregister_pickle_by_value(module)
    if len(snapshot) > MAX_INPUT:
        raise ValueError('execution snapshot exceeds input cap')
    return cloudpickle.loads(snapshot), hashlib.sha256(snapshot).hexdigest(), identities
