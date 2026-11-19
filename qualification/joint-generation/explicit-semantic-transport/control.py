"""Opt-in finite RGB command-support conditioning of an existing output law.

No target labels, renderer, model updates or inferred commands are accepted.
This is a new serving profile, not the original generator or a training gradient.
Support is defined by observed decoded semantics, never trusted latent IDs.
"""
from dataclasses import dataclass
import hashlib
import json
import math

SCHEMA = 'rgb-decoded-command-support-v1'
MODE = 'explicit-request-words'
VOCABULARY = ('red', 'green', 'blue', 'square', 'cross', 'left', 'right')
CLASSES = 12


def _digest(value):
    if type(value) is not str or len(value) != 64 or any(c not in '0123456789abcdef' for c in value):
        raise ValueError('explicit lowercase model digest required')
    return value


def _canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False)


@dataclass(frozen=True)
class Command:
    """Zero is the legacy keep word; this filter adds no constraint on that axis.

    Preservation of unspecified source attributes is evaluated, not guaranteed.
    Positive values select the declared explicit word index."""
    color: int
    shape: int
    position: int

    def __post_init__(self):
        for value, maximum in zip(self.values, (3, 2, 2)):
            if type(value) is not int or not 0 <= value <= maximum:
                raise ValueError('exact supported request words required')

    @property
    def values(self):
        return (self.color, self.shape, self.position)

    @classmethod
    def from_features(cls, features):
        """Parse only the ten explicit one-hot instruction features, not x/labels."""
        if len(features) != 10:
            raise ValueError('ten instruction features required')
        commands = []
        for block in (features[:4], features[4:7], features[7:]):
            if any(type(v) not in (int, float) or v not in (0, 1) for v in block) or sum(block) != 1:
                raise ValueError('exact one-hot request block required')
            commands.append(list(block).index(1))
        return cls(*commands)

    def permits(self, semantic_id):
        if type(semantic_id) is not int or not 0 <= semantic_id < CLASSES:
            raise ValueError('observed finite scene semantics required')
        attrs = (semantic_id // 4, (semantic_id // 2) % 2, semantic_id % 2)
        return all(word == 0 or value == word - 1 for word, value in zip(self.values, attrs))


def _policy(values):
    if type(values) is not tuple or len(values) != CLASSES:
        raise ValueError('immutable twelve-class policy required')
    if any(type(x) not in (int, float) or not math.isfinite(x) or x < 0 for x in values):
        raise ValueError('finite nonnegative probabilities required')
    if abs(math.fsum(values) - 1) > 1e-10:
        raise ValueError('normalized input policy required')
    return values


class UnsupportedCommand(ValueError):
    """No decoded support or no probability mass; caller must not silently fallback."""


@dataclass(frozen=True)
class ControlProfile:
    model_sha256: str
    text_semantics: tuple
    image_semantics: tuple
    mode: str

    def __post_init__(self):
        _digest(self.model_sha256)
        if self.mode != MODE:
            raise ValueError('explicit command serving profile required')
        for semantics in (self.text_semantics, self.image_semantics):
            if type(semantics) is not tuple or len(semantics) != CLASSES or any(
                    type(v) is not int or not 0 <= v < CLASSES for v in semantics):
                raise ValueError('exact observed decoder semantics inventory required')

    def metadata(self):
        return dict(schema=SCHEMA, mode=self.mode, model_sha256=self.model_sha256,
                    vocabulary=list(VOCABULARY), text_semantics=list(self.text_semantics),
                    image_semantics=list(self.image_semantics))

    @property
    def key(self):
        return hashlib.sha256(_canonical(self.metadata()).encode()).hexdigest()

    def dumps(self):
        return _canonical(dict(profile=self.metadata(), profile_key=self.key))

    @classmethod
    def loads(cls, payload, *, expected_model_sha256, expected_mode):
        if type(payload) is not str or len(payload.encode()) > 8192:
            raise ValueError('bounded explicit profile document required')
        def unique(pairs):
            result = {}
            for key, value in pairs:
                if key in result:
                    raise ValueError('duplicate profile field')
                result[key] = value
            return result
        value = json.loads(payload, object_pairs_hook=unique)
        if type(value) is not dict or set(value) != {'profile', 'profile_key'}:
            raise ValueError('exact profile envelope required')
        p = value['profile']
        if (type(p) is not dict or set(p) != {'schema', 'mode', 'model_sha256', 'vocabulary', 'text_semantics', 'image_semantics'}
                or p['schema'] != SCHEMA or p['vocabulary'] != list(VOCABULARY)
                or p['mode'] != expected_mode or expected_mode != MODE
                or p['model_sha256'] != _digest(expected_model_sha256)):
            raise ValueError('explicit profile/schema/vocabulary/model binding mismatch')
        result = cls(p['model_sha256'], tuple(p['text_semantics']), tuple(p['image_semantics']), p['mode'])
        if value['profile_key'] != result.key:
            raise ValueError('altered profile identity')
        return result

    def condition(self, text, image, command, *, observed_model_sha256):
        if observed_model_sha256 != self.model_sha256 or type(command) is not Command:
            raise ValueError('bound unchanged model and explicit request command required')
        text, image = _policy(text), _policy(image)
        def project(policy, semantics):
            mask = tuple(command.permits(k) for k in semantics)
            mass = math.fsum(p for p, allowed in zip(policy, mask) if allowed)
            if not any(mask) or mass <= 0:
                raise UnsupportedCommand('requested words have no supported decoded mass')
            # Preserve the exact law when no observed outcomes are excluded.
            answer = policy if all(mask) else tuple(p / mass if yes else 0.0 for p, yes in zip(policy, mask))
            return answer, mass, sum(mask)
        pt, mt, nt = project(text, self.text_semantics)
        pi, mi, ni = project(image, self.image_semantics)
        return dict(text=pt, image=pi, retained_text_mass=mt, retained_image_mass=mi,
                    supported_text_outcomes=nt, supported_image_outcomes=ni,
                    profile_key=self.key, command=command.values)
