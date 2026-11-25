"""Reuse identical differentiable dense operators within a frozen control epoch."""
from common import ModelConfig, SmallHCSN, torch


class CachedSmallHCSN(SmallHCSN):
    """The physical equations, clock, writes, remaps and state contract are unchanged."""
    def forward(self, x, return_features=False, state=None):
        self._operator_cache = {}
        self._action_step = 0 if state is None else state.step
        self.operator_evaluations = 0
        self.operator_cache_hits = 0
        try:
            return super().forward(x, return_features=return_features, state=state)
        finally:
            self._operator_cache = None

    def _flow(self, *args, **kwargs):
        result = super()._flow(*args, **kwargs)
        self._action_step += 1
        return result

    def _action(self, matrix, vectors, rate, duration, column=False):
        if self.config.backend != "dense" or getattr(self, "_operator_cache", None) is None:
            return super()._action(matrix, vectors, rate, duration, column)
        # Q, boundary and cost are unchanged until the next scheduled control refresh.
        key = (self._action_step // self.config.slow_every, column, matrix.shape[-1], duration)
        if key not in self._operator_cache:
            self._operator_cache[key] = torch.matrix_exp(matrix * duration)
            self.operator_evaluations += 1
        else:
            self.operator_cache_hits += 1
        action = self._operator_cache[key]
        return action @ vectors if column else vectors @ action


def make_model(width, seed, bank="value_risk", message="full", connection="learned"):
    torch.manual_seed(seed + 101 * width)
    model = CachedSmallHCSN(ModelConfig(neurons=width, precision="float64", backend="dense",
                                       feature_bank=bank, message_mode=message))
    model.recurrent.weight.requires_grad_(connection == "learned")
    return model
