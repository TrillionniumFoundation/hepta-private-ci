"""Tensor-state and process measurements with explicit measurement scope."""

import sys


def tensor_bytes(value):
    """Count tensor payloads, counting aliased storage only once."""
    storages = {}

    def visit(item):
        if isinstance(item, dict):
            for child in item.values():
                visit(child)
        elif isinstance(item, (tuple, list)):
            for child in item:
                visit(child)
        elif hasattr(item, "untyped_storage"):
            storage = item.untyped_storage()
            storages[(str(item.device), storage.data_ptr())] = storage.nbytes()
    visit(value)
    return sum(storages.values())


def persistent_state(encoder, batch, torch):
    """Measure the actual retained state of the supported streaming encoders."""
    from .cells import ValueKernelCell
    from .baselines import GRUEncoder

    if isinstance(encoder, ValueKernelCell):
        state = encoder.initial_state(len(batch), like=batch)
        return dict(bytes=tensor_bytes(state), batch_size=len(batch),
                    components=["memory", "recovery"], includes_density_and_delay=False,
                    scope="complete retained HX feature-cell tensor state; no spiking queue")
    if isinstance(encoder, GRUEncoder):
        state = batch.new_zeros(encoder.gru.num_layers, len(batch), encoder.gru.hidden_size)
        return dict(bytes=tensor_bytes(state), batch_size=len(batch), components=["hidden"],
                    includes_density_and_delay=False, scope="complete retained GRU tensor state")
    return dict(bytes=None, scope="not measured for this encoder")


def process_peak_rss():
    """OS high-water mark; per-fit only when the fit has its own fresh process."""
    try:
        import resource
        value = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        return dict(bytes=int(value if sys.platform == "darwin" else value * 1024),
                    scope="process lifetime high-water RSS; includes interpreter and libraries")
    except (ImportError, OSError, AttributeError) as error:
        return dict(bytes=None, scope="process lifetime high-water RSS",
                    reason=f"{type(error).__name__}: {error}")
