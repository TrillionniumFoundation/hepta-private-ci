"""Immutable prepared arithmetic for an existing outcome router, NOT authority.

Validate/copy the 265 weights once per frozen policy and retain exact fsum order.
Every use still checks model/calibration/scope/generation and the request binding.
Preparation is paid separately; this object neither caches decisions nor learns.
"""
from dataclasses import dataclass
import hashlib
import math
from four_gate_common import canonical, digest, require, sha

PROFILE = 'prepared_gate_v2'
CONTEXT = ('model', 'calibration', 'scope', 'generation')


@dataclass(frozen=True, slots=True, init=False)
class PreparedOutcomeGate:
    """Owned tuple snapshots; mutation of caller lists cannot change inference.

    Application-internal immutability, not a security boundary against arbitrary
    Python code. No pickle, dynamic code generation, global cache or input labels.
    """
    kind: str
    context: tuple
    threshold: float
    layers: tuple
    suffix: bytes
    identity: str

    def __init__(self, state, threshold, context, *, kind='learned'):
        require(kind in ('learned', 'confidence'), 'prepared gate kind')
        require(type(context) is dict and set(context) == set(CONTEXT), 'complete gate context')
        sha(context['model']); sha(context['calibration'])
        require(type(context['scope']) is str and 0 < len(context['scope']) <= 256 and
                type(context['generation']) is int and context['generation'] > 0, 'gate scope/generation')
        require(type(threshold) in (int, float) and math.isfinite(threshold) and
                0 <= threshold <= 1.01, 'finite gate threshold')
        shapes = {'value.weight': (8, 15), 'gate.weight': (8, 15), 'out.weight': (1, 8),
                  'value.bias': (8,), 'gate.bias': (8,), 'out.bias': (1,)}
        copied = None
        if kind == 'learned':
            require(type(state) is dict and set(state) == set(shapes), 'complete gate tensors')
            copied = {}
            for name, shape in shapes.items():
                values = state[name]
                require(type(values) is list and len(values) == shape[0], 'gate tensor shape')
                if len(shape) == 2:
                    require(all(type(row) is list and len(row) == shape[1] for row in values), 'gate tensor shape')
                    require(all(type(v) in (int, float) and math.isfinite(v) for row in values for v in row),
                            'finite gate tensor')
                    copied[name] = tuple(tuple(row) for row in values)
                else:
                    require(all(type(v) in (int, float) and math.isfinite(v) for v in values), 'finite gate tensor')
                    copied[name] = tuple(values)
        else:
            require(state is None, 'confidence has no neural weights')
        layers = () if copied is None else tuple((copied[n+'.weight'], copied[n+'.bias'])
                                                  for n in ('value', 'gate', 'out'))
        # Exact canonical suffix of the OLD request bundle, not a replacement ID.
        suffix = b',"state":' + canonical(copied) + b',"threshold":' + canonical(threshold) + b'}'
        identity = digest({'profile': PROFILE, 'kind': kind, 'context': context,
                           'state': copied, 'threshold': threshold})
        for key, value in dict(kind=kind, context=tuple(context[k] for k in CONTEXT),
                               threshold=threshold, layers=layers, suffix=suffix, identity=identity).items():
            object.__setattr__(self, key, value)

    def bind(self, problem, context):
        """Check current request before calculating its old byte-identical bundle ID."""
        require(type(context) is dict and set(context) == {'source', *CONTEXT}, 'complete request context')
        require(tuple(context[k] for k in CONTEXT) == self.context, 'stale or cross-scope gate')
        sha(context['source'])
        binding = digest(context)
        require(binding == problem.binding, 'prepared request binding mismatch')
        return hashlib.sha256(b'{"binding":' + canonical(binding) + self.suffix).hexdigest()

    def score(self, values):
        require(type(values) is list and len(values) == 15 and
                all(type(v) in (int, float) and math.isfinite(v) for v in values), 'finite gate features')
        if self.kind == 'confidence':
            # Preserve the inherited finite score, including tiny roundoff past 0/1.
            # The belief owner validates its probability law; no clipping here.
            return 1-values[0]
        def affine(layer, x):
            weights, bias = layer
            return [math.fsum(a*v for a, v in zip(row, x))+b for row, b in zip(weights, bias)]
        def sigmoid(x):
            require(math.isfinite(x), 'nonfinite gate logit')
            return 1/(1+math.exp(-x)) if x >= 0 else math.exp(x)/(1+math.exp(x))
        v, g = affine(self.layers[0], values), affine(self.layers[1], values)
        return sigmoid(affine(self.layers[2], [math.tanh(a)*sigmoid(b) for a, b in zip(v, g)])[0])
