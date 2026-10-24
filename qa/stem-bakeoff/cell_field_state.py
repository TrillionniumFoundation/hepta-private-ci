"""Replayable research Adam state over the existing immutable-feature Cell head.

The serving artifact remains unchanged. This separate checkpoint retains every
variable used by the declared finite optimizer and its PCG64 minibatch sampler.
Hashes establish local identity, not source authentication or authority.
"""

import copy
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import zipfile

import numpy as np

from cell_learning_models import NumpyCellHead, canonical, normalize_features


SCHEMA = "hepta.cell-field-training-state.v1"
DEFAULT_PROTOCOL = {
    "optimizer": "adam", "learning_rate": 0.02, "l2": 0.001,
    "beta1": 0.9, "beta2": 0.999, "epsilon": 1e-8, "gradient_clip": 5.0,
    "sampler": "full_batch", "batch_size": 32,
    "normalization": "l2_times_sqrt_width",
    "intervention": "post-adam-additive-parameter-increment",
}


def _json_copy(value):
    return json.loads(canonical(value))


def _array_digest(value):
    value = np.ascontiguousarray(value)
    return hashlib.sha256(canonical([value.dtype.str, list(value.shape)])
                          + value.tobytes()).hexdigest()


def dataset_digest(features, labels):
    """Identity of the float64/int64 training inputs, before normalization."""
    x, y = _validate_data(features, labels)
    return hashlib.sha256(canonical([_array_digest(x), _array_digest(y)])).hexdigest()


def _validate_data(features, labels, width=None, classes=None):
    x, y = np.asarray(features, dtype=np.float64), np.asarray(labels)
    if (x.ndim != 2 or not 1 <= len(x) <= 16384 or not 1 <= x.shape[1] <= 4096
            or x.size > 8_388_608 or not np.isfinite(x).all()
            or y.shape != (len(x),) or y.dtype.kind not in "iu"
            or np.any(y < 0) or (width is not None and x.shape[1] != width)
            or (classes is not None and np.any(y >= classes))):
        raise ValueError("bounded finite features and integer class labels required")
    return np.ascontiguousarray(x), np.ascontiguousarray(y, dtype=np.int64)


def _protocol(value):
    result = {**DEFAULT_PROTOCOL, **(value or {})}
    if set(result) != set(DEFAULT_PROTOCOL):
        raise ValueError("unknown optimizer protocol field")
    for key in ("learning_rate", "l2", "beta1", "beta2", "epsilon", "gradient_clip"):
        number = result[key]
        if type(number) not in (int, float) or not np.isfinite(number):
            raise ValueError("finite scalar optimizer protocol required")
    if (result["optimizer"] != "adam" or not 0 < result["learning_rate"] <= 1
            or not 0 <= result["l2"] <= 1 or not 0 <= result["beta1"] < 1
            or not 0 <= result["beta2"] < 1 or not 0 < result["epsilon"] <= 1
            or not 0 < result["gradient_clip"] <= 1e6
            or result["sampler"] not in ("full_batch", "iid_with_replacement")
            or type(result["batch_size"]) is not int or not 1 <= result["batch_size"] <= 16384
            or result["normalization"] != DEFAULT_PROTOCOL["normalization"]
            or result["intervention"] != DEFAULT_PROTOCOL["intervention"]):
        raise ValueError("invalid declared Adam or sampling protocol")
    return _json_copy(result)


class CellTrainingState:
    """Complete finite Adam state; explicit context changes preserve moments.

    Contexts map predeclared names to ``dataset_digest`` values. If omitted, the
    first advance binds a single ``train`` context. All later byte changes reject.
    Full-state vectors concatenate theta, m, v, each in sorted parameter order.
    """

    def __init__(self, head, *, bindings, protocol=None, seed=0, contexts=None,
                 active_context=None):
        if (type(head) is not NumpyCellHead or not isinstance(bindings, dict) or not bindings
                or type(seed) is not int or not 0 <= seed < 2**64):
            raise ValueError("existing Cell head, nonempty bindings and sampler seed required")
        self.head = copy.deepcopy(head)
        self._protocol, self._bindings = _protocol(protocol), _json_copy(bindings)
        if len(canonical(self.bindings)) > 262144:
            raise ValueError("oversized training identity")
        self._contexts = _json_copy(contexts or {})
        if (not isinstance(self.contexts, dict) or len(self.contexts) > 32
                or any(not isinstance(k, str) or not k or len(k) > 128
                       or not isinstance(v, str) or len(v) != 64
                       or any(c not in "0123456789abcdef" for c in v)
                       for k, v in self.contexts.items())):
            raise ValueError("bounded context names and SHA256 dataset identities required")
        self.active_context = active_context or (next(iter(self.contexts)) if self.contexts else "train")
        if (not isinstance(self.active_context, str) or len(self.active_context) > 128
                or (self.contexts and self.active_context not in self.contexts)):
            raise ValueError("active training context is undeclared")
        self.names = tuple(sorted(self.head.params))
        self.m = {key: np.zeros_like(self.head.params[key]) for key in self.names}
        self.v = {key: np.zeros_like(self.head.params[key]) for key in self.names}
        self.step_count, self.sampler_draw_count, self.external_batch_count = 0, 0, 0
        self.rng = np.random.Generator(np.random.PCG64(seed))

    @property
    def protocol(self):
        return _json_copy(self._protocol)

    @property
    def bindings(self):
        return _json_copy(self._bindings)

    @property
    def contexts(self):
        return _json_copy(self._contexts)

    @property
    def parameter_count(self):
        return self.head.parameter_count

    def parameter_vector(self):
        return np.concatenate([self.head.params[name].ravel() for name in self.names])

    def vector(self):
        return np.concatenate([values[name].ravel()
                               for values in (self.head.params, self.m, self.v)
                               for name in self.names])

    def _unpack(self, vector):
        value = np.asarray(vector, dtype=np.float64)
        n = self.parameter_count
        if (value.shape != (3 * n,) or not np.isfinite(value).all()
                or np.any(value[2 * n:] < 0)):
            raise ValueError("complete finite theta/m/v vector with nonnegative v required")
        groups, offset = [], 0
        for _ in range(3):
            group = {}
            for name in self.names:
                template = self.head.params[name]
                group[name] = value[offset:offset + template.size].reshape(template.shape).copy()
                offset += template.size
            groups.append(group)
        return groups

    def set_vector(self, vector):
        self.head.params, self.m, self.v = self._unpack(vector)

    def head_from_vector(self, vector):
        head = copy.deepcopy(self.head)
        head.params = self._unpack(vector)[0]
        return head

    def clone(self):
        return copy.deepcopy(self)

    def select_context(self, name):
        if name not in self.contexts:
            raise ValueError("cannot select an undeclared training context")
        self.active_context = name

    def _marks(self, indices, rows):
        if indices is None:
            return np.arange(rows, dtype=np.int64)
        marks = np.asarray(indices)
        if (marks.ndim != 1 or not 1 <= len(marks) <= 16384
                or marks.dtype.kind not in "iu" or np.any(marks < 0) or np.any(marks >= rows)):
            raise ValueError("bounded in-range integer minibatch marks required")
        return marks.astype(np.int64, copy=True)

    def transition_vector(self, vector, step_count, features, labels, indices=None):
        """Pure complete update; None means full batch and consumes no random state.

        Explicit marks support paired finite minibatch laws. The per-minibatch
        inverse-class-frequency weighting is inherited from the existing head;
        it must not be described as an unbiased full-dataset gradient in general.
        """
        if type(step_count) is not int or not 0 <= step_count < 1_000_000_000:
            raise ValueError("bounded nonnegative completed step count required")
        params, m, v = self._unpack(vector)
        x, y = _validate_data(features, labels, self.head.width, self.head.classes)
        marks = self._marks(indices, len(y))
        head = copy.deepcopy(self.head)
        head.params = params
        loss, gradient = head.loss_gradients(normalize_features(x)[marks], y[marks], self.protocol["l2"])
        norm = np.sqrt(sum(float(np.square(g).sum()) for g in gradient.values()))
        if not np.isfinite(loss) or not np.isfinite(norm):
            raise ValueError("nonfinite optimizer objective or gradient")
        clip = min(1.0, self.protocol["gradient_clip"] / max(norm, 1e-12))
        b1, b2, step = self.protocol["beta1"], self.protocol["beta2"], step_count + 1
        # Preserve the legacy literal .1/.001 operations at the default betas.
        c1, c2 = (float(Decimal(1) - Decimal(str(beta))) for beta in (b1, b2))
        for name in self.names:
            g = gradient[name] * clip
            m[name] = b1 * m[name] + c1 * g
            v[name] = b2 * v[name] + c2 * g * g
            corrected_m, corrected_v = m[name] / (1 - b1**step), v[name] / (1 - b2**step)
            params[name] -= self.protocol["learning_rate"] * corrected_m / (
                np.sqrt(corrected_v) + self.protocol["epsilon"])
        result = np.concatenate([group[name].ravel() for group in (params, m, v) for name in self.names])
        self._unpack(result)
        return result

    def advance(self, features, labels, *, indices=None, intervention=None, mask=None):
        """Publish one local transition only after all inputs and results validate."""
        x, y = _validate_data(features, labels, self.head.width, self.head.classes)
        data_id = dataset_digest(x, y)
        if self.contexts and self.contexts.get(self.active_context) != data_id:
            raise ValueError("training bytes differ from the selected context")
        delta = np.zeros(self.parameter_count) if intervention is None else np.asarray(intervention, dtype=np.float64)
        if delta.shape != (self.parameter_count,) or not np.isfinite(delta).all():
            raise ValueError("finite parameter-shaped physical intervention required")
        delta_norm = float(np.linalg.norm(delta))
        if not np.isfinite(delta_norm):
            raise ValueError("intervention norm overflows")
        if mask is not None:
            mask = np.asarray(mask)
            if (mask.dtype != np.bool_ or mask.shape != delta.shape or np.any(delta[~mask] != 0)):
                raise ValueError("intervention exceeds its declared parameter mask")
        before, rng = self.digest(), copy.deepcopy(self.rng)
        draws, external = 0, 0
        if indices is not None:
            marks, origin, external = self._marks(indices, len(y)), "external", 1
        elif self.protocol["sampler"] == "iid_with_replacement":
            draws = self.protocol["batch_size"]
            marks, origin = rng.integers(0, len(y), size=draws, dtype=np.int64), "pcg64-iid"
        else:
            marks, origin = self._marks(None, len(y)), "full_batch"
        previous = self.vector()
        candidate = self.transition_vector(previous, self.step_count, x, y, marks)
        candidate[:self.parameter_count] += delta
        self._unpack(candidate)
        update_norm = float(np.linalg.norm(candidate[:self.parameter_count] - previous[:self.parameter_count]))
        if not np.isfinite(update_norm):
            raise ValueError("parameter update norm overflows")
        if not self.contexts:
            self._contexts = {self.active_context: data_id}
        self.set_vector(candidate)
        self.step_count += 1
        self.rng = rng
        self.sampler_draw_count += draws
        self.external_batch_count += external
        return {"previous_state_sha256": before, "state_sha256": self.digest(),
                "step": self.step_count, "context": self.active_context,
                "dataset_sha256": data_id, "marks": marks.tolist(), "mark_origin": origin,
                "intervention_sha256": _array_digest(delta),
                "mask_sha256": _array_digest(mask) if mask is not None else None,
                "intervention_l2": delta_norm, "parameter_update_l2": update_norm,
                "authority": "DENY_ALL"}

    def _metadata(self):
        return {"schema": SCHEMA, "head": {key: getattr(self.head, key)
                                            for key in ("width", "classes", "mode", "rank", "max_parameters")},
                "protocol": self.protocol, "bindings": self.bindings, "contexts": self.contexts,
                "active_context": self.active_context, "step_count": self.step_count,
                "sampler_draw_count": self.sampler_draw_count,
                "external_batch_count": self.external_batch_count,
                "rng": self.rng.bit_generator.state, "parameter_names": list(self.names)}

    def digest(self):
        return hashlib.sha256(canonical(self._metadata()) + bytes.fromhex(_array_digest(self.vector()))).hexdigest()

    def save(self, directory):
        self._unpack(self.vector())
        target = Path(directory)
        target.mkdir(parents=True, exist_ok=False)
        arrays = {f"{group}__{name}": values[name]
                  for group, values in (("theta", self.head.params), ("m", self.m), ("v", self.v))
                  for name in self.names}
        with (target / "state.npz").open("xb") as stream:
            np.savez_compressed(stream, **arrays)
        payload = (target / "state.npz").read_bytes()
        manifest = {**self._metadata(), "state_sha256": self.digest(),
                    "payload_sha256": hashlib.sha256(payload).hexdigest(),
                    "tensor_sha256": {name: _array_digest(value) for name, value in arrays.items()},
                    "retained_tensor_bytes": sum(value.nbytes for value in arrays.values()),
                    "authority": "DENY_ALL"}
        (target / "manifest.json").write_bytes(canonical(manifest) + b"\n")
        return manifest

    @classmethod
    def load(cls, directory, expected_bindings, expected_protocol=None, expected_contexts=None,
             expected_state_digest=None):
        target = Path(directory)
        metadata, payload = target / "manifest.json", target / "state.npz"
        if (target.is_symlink() or metadata.is_symlink() or payload.is_symlink()
                or metadata.stat().st_size > 1_048_576 or payload.stat().st_size > 64 * 1024**2):
            raise ValueError("unsupported or oversized training checkpoint")
        manifest = json.loads(metadata.read_bytes())
        if (manifest.get("schema") != SCHEMA or manifest.get("authority") != "DENY_ALL"
                or canonical(manifest.get("bindings")) != canonical(expected_bindings)
                or (expected_protocol is not None and manifest.get("protocol") != _protocol(expected_protocol))
                or (expected_contexts is not None and manifest.get("contexts") != expected_contexts)
                or (expected_state_digest is not None and manifest.get("state_sha256") != expected_state_digest)
                or hashlib.sha256(payload.read_bytes()).hexdigest() != manifest.get("payload_sha256")):
            raise ValueError("checkpoint identity or payload mismatch")
        state = cls(NumpyCellHead(**manifest["head"]), bindings=expected_bindings,
                    protocol=manifest["protocol"], contexts=manifest["contexts"],
                    active_context=manifest["active_context"])
        expected = {f"{group}__{name}" for group in ("theta", "m", "v") for name in state.names}
        with zipfile.ZipFile(payload) as archive:
            if (len(archive.infolist()) != len(expected)
                    or sum(item.file_size for item in archive.infolist()) > 32 * 1024**2):
                raise ValueError("unexpected checkpoint tensor archive")
        values = []
        with np.load(payload, allow_pickle=False) as arrays:
            if set(arrays.files) != expected or set(manifest.get("tensor_sha256", {})) != expected:
                raise ValueError("unexpected checkpoint tensors")
            for group in ("theta", "m", "v"):
                for name in state.names:
                    key, template = f"{group}__{name}", state.head.params[name]
                    value = arrays[key]
                    if (value.dtype != np.float64 or value.shape != template.shape
                            or _array_digest(value) != manifest["tensor_sha256"][key]):
                        raise ValueError("training tensor shape, precision or checksum mismatch")
                    values.append(value.ravel())
        state.set_vector(np.concatenate(values))
        for key in ("step_count", "sampler_draw_count", "external_batch_count"):
            value = manifest[key]
            if type(value) is not int or not 0 <= value < 2**63:
                raise ValueError("invalid checkpoint counter")
            setattr(state, key, value)
        if manifest["rng"].get("bit_generator") != "PCG64":
            raise ValueError("checkpoint sampler differs")
        state.rng.bit_generator.state = manifest["rng"]
        if (manifest["parameter_names"] != list(state.names)
                or state.digest() != manifest["state_sha256"]
                or manifest["retained_tensor_bytes"] != state.vector().nbytes):
            raise ValueError("complete training state checksum mismatch")
        return state
