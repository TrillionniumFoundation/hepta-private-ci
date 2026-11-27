"""Input-driven finite population research models with explicit approximation laws."""

__all__ = ["BatchedFlow", "FlowConfig", "FlowState"]


def __getattr__(name):
    if name in __all__:
        from . import batched_flow
        return getattr(batched_flow, name)
    raise AttributeError(name)
