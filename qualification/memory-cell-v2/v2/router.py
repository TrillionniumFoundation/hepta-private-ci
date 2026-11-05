"""Research addressing with separate typed, public-schema and learned routes.

The learned model generalizes word order and question wording around trained
lexical cues. It is not a pretrained language model or a guarantee of open-world
rejection. Its inference never reads RouteRequest.cell_type or an oracle label.
Vocabulary and schema bytes are part of the artifact cost, not free parameters.
"""

from dataclasses import asdict, dataclass
import hashlib
import io
import json
from pathlib import Path
import re
import time
import unicodedata

import numpy as np


def _canonical(value):
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")


def _norm(value):
    if not isinstance(value, str):
        raise ValueError("text fields must be strings")
    return unicodedata.normalize("NFKC", value).casefold()


def _identifier(value):
    value = _norm(value)
    if not 1 <= len(value) <= 128 or re.fullmatch(r"[\w.-]+", value) is None:
        raise ValueError("invalid scope, route or type identifier")
    return value


def _unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate manifest field")
        result[key] = value
    return result


@dataclass(frozen=True)
class RouteSpec:
    route_id: str
    cell_type: str
    aliases: tuple[str, ...] = ()


@dataclass(frozen=True)
class RouteRequest:
    text: str
    scope: str = "research"
    cell_type: str | None = None


@dataclass(frozen=True)
class RoutingDecision:
    route_id: str | None
    reason: str
    confidence: float | None
    method: str


class Router:
    """No answer values or key-to-answer mappings enter this address classifier."""

    def __init__(self, specs, scope="research", seed=8001, threshold=0.8, margin=0.25):
        if not isinstance(specs, (list, tuple)) or not 1 <= len(specs) <= 64:
            raise ValueError("provide 1..64 route specifications")
        if type(seed) is not int or not 0 <= seed < 2**32:
            raise ValueError("seed must be a uint32 integer")
        if any(not np.isfinite(x) or not 0 <= x <= 1 for x in (threshold, margin)):
            raise ValueError("threshold and margin must be finite in [0, 1]")
        normalized = []
        for spec in specs:
            if (
                not isinstance(spec, RouteSpec)
                or not isinstance(spec.aliases, (list, tuple))
                or len(spec.aliases) > 32
            ):
                raise ValueError("invalid route specification")
            aliases = tuple(" ".join(_norm(alias).split()) for alias in spec.aliases)
            if any(not 1 <= len(alias) <= 128 for alias in aliases):
                raise ValueError("aliases must contain 1..128 characters")
            normalized.append(
                RouteSpec(
                    _identifier(spec.route_id), _identifier(spec.cell_type), aliases
                )
            )
        self.specs = tuple(normalized)
        self.routes = tuple(spec.route_id for spec in self.specs)
        if len(set(self.routes)) != len(self.routes):
            raise ValueError("duplicate normalized route identifiers")
        self.scope, self.seed = _identifier(scope), seed
        self.threshold, self.margin = float(threshold), float(margin)
        self.types, aliases = {}, {}
        for spec in self.specs:
            self.types.setdefault(spec.cell_type, set()).add(spec.route_id)
            for alias in (spec.route_id, spec.cell_type, *spec.aliases):
                aliases.setdefault(alias, set()).add(spec.route_id)
        # A final period is punctuation; a dot before identifier characters is not.
        self.patterns = [
            (
                re.compile(
                    r"(?<![\w.-])"
                    + re.escape(alias).replace(r"\ ", r"\s+")
                    + r"(?![\w-]|\.(?=[\w.-]))"
                ),
                routes,
            )
            for alias, routes in sorted(aliases.items())
        ]
        self.vocabulary = ()
        self.weights = np.zeros((0, len(self.routes) + 1), dtype=np.float64)
        self.training_digest = None
        self.training_examples = self.training_families = 0

    @property
    def parameter_bytes(self):
        return self.weights.nbytes

    @property
    def trainable_params(self):
        return self.weights.size

    def _tokens(self, text):
        tokens = set(re.findall(r"[\w.-]+", _norm(text)))
        public_ids = set(self.routes) | set(self.types)
        return {
            token.rstrip(".")
            for token in tokens
            if len(token) <= 128
            and (
                token in public_ids
                or (
                    any(char.isalpha() for char in token)
                    and not any(char.isdigit() for char in token)
                )
            )
        }

    def _inspect(self, text):
        normalized = _norm(text)
        heads = re.findall(
            r"(?<![\w.-])(?:scope|type|cell_type|domain|route)\s*[:=]", normalized
        )
        declarations = re.findall(
            r"(?<![\w.-])(scope|type|cell_type|domain|route)\s*[:=]\s*([^\s,;\]}]+)",
            normalized,
        )
        if len(heads) != len(declarations):
            return set(), "malformed_declaration"
        groups = []
        for kind, raw in declarations:
            value = raw.rstrip(".!?")
            if kind == "scope":
                if value != self.scope:
                    return set(), "unknown_scope"
            elif kind in ("type", "cell_type"):
                if value not in self.types:
                    return set(), "unknown_type"
                groups.append(self.types[value])
            else:
                if value not in self.routes:
                    return set(), "unknown_route"
                groups.append({value})
        groups.extend(
            routes for pattern, routes in self.patterns if pattern.search(normalized)
        )
        candidates = set.intersection(*groups) if groups else set()
        if groups and len(candidates) != 1:
            return candidates, "ambiguous_address"
        return candidates, None

    def _features(self, texts):
        indices = {token: index for index, token in enumerate(self.vocabulary)}
        result = np.zeros((len(texts), len(indices)), dtype=np.float64)
        for row, text in enumerate(texts):
            for token in self._tokens(text):
                if token in indices:
                    result[row, indices[token]] = 1.0
        norm = np.linalg.norm(result, axis=1, keepdims=True)
        return result / np.maximum(norm, 1.0)

    @staticmethod
    def _proba(features, weights):
        logits = features @ weights
        logits -= logits.max(axis=1, keepdims=True)
        values = np.exp(logits)
        return values / values.sum(axis=1, keepdims=True)

    def fit(self, texts, labels, *, families, steps=600, lr=0.03):
        """Train on separately supplied route labels; None is the reject class.

        Each of at least two independent wording families must cover every class,
        including rejects. Family/class-balanced loss prevents template priors;
        vocabulary retains cues with >=80% label purity across >=2 families.
        Callers must keep selection/test queries outside this training interface.
        """
        started = time.perf_counter()
        if not isinstance(texts, (list, tuple)) or not 1 <= len(texts) <= 8192:
            raise ValueError("provide 1..8192 training texts")
        if len(labels) != len(texts) or len(families) != len(texts):
            raise ValueError("texts, labels and families must align")
        if any(
            not isinstance(text, str) or not text.strip() or len(text) > 16384
            for text in texts
        ):
            raise ValueError("invalid training text")
        if sum(len(text) for text in texts) > 2**20:
            raise ValueError("training text exceeds the bounded development interface")
        if (
            type(steps) is not int
            or not 1 <= steps <= 10000
            or not np.isfinite(lr)
            or not 0 < lr <= 1
        ):
            raise ValueError("invalid training schedule")
        classes = (*self.routes, None)
        if any(label not in classes for label in labels):
            raise ValueError("unknown training route label")
        if any(
            not isinstance(family, str) or not 1 <= len(family) <= 128
            for family in families
        ):
            raise ValueError("invalid family identifier")
        family_names = set(families)
        if not 2 <= len(family_names) <= 64:
            raise ValueError("at least two wording families are required")
        counts = {(family, label): 0 for family in family_names for label in classes}
        for family, label in zip(families, labels):
            counts[family, label] += 1
        if any(count == 0 for count in counts.values()):
            raise ValueError("every family must cover every route and reject class")
        sample_weights = np.array(
            [1 / counts[family, label] for family, label in zip(families, labels)]
        )
        sample_weights /= sample_weights.sum()
        targets = np.array([classes.index(label) for label in labels])
        frequencies, seen_families = {}, {}
        for text, target, family, weight in zip(
            texts, targets, families, sample_weights
        ):
            for token in self._tokens(text):
                frequencies.setdefault(token, np.zeros(len(classes)))[target] += weight
                seen_families.setdefault((token, int(target)), set()).add(family)
        candidates, owners = [], set()
        for token, frequency in frequencies.items():
            owner = int(frequency.argmax())
            purity = frequency[owner] / frequency.sum()
            if purity >= 0.8 and len(seen_families[token, owner]) >= 2:
                candidates.append((float(frequency[owner]), token, owner))
        chosen = sorted(candidates, key=lambda item: (-item[0], item[1]))[:512]
        owners.update(owner for _, _, owner in chosen)
        if owners != set(range(len(classes))):
            raise ValueError(
                "training lacks stable lexical evidence for one or more classes"
            )
        self.vocabulary = tuple(sorted(token for _, token, _ in chosen))
        features = self._features(texts)
        weights = np.random.default_rng(self.seed).normal(
            0, 0.01, (features.shape[1], len(classes))
        )
        first, second = np.zeros_like(weights), np.zeros_like(weights)
        initial_loss = None
        for step in range(1, steps + 1):
            probabilities = self._proba(features, weights)
            if initial_loss is None:
                initial_loss = float(
                    -np.sum(
                        sample_weights
                        * np.log(
                            np.maximum(
                                probabilities[np.arange(len(texts)), targets], 1e-300
                            )
                        )
                    )
                )
            probabilities[np.arange(len(texts)), targets] -= 1
            gradient = (
                features.T @ (probabilities * sample_weights[:, None]) + 1e-4 * weights
            )
            first = 0.9 * first + 0.1 * gradient
            second = 0.999 * second + 0.001 * gradient**2
            weights -= (
                lr
                * (first / (1 - 0.9**step))
                / (np.sqrt(second / (1 - 0.999**step)) + 1e-8)
            )
        if not np.isfinite(weights).all():
            raise ValueError("training produced nonfinite weights")
        self.weights = weights
        final = self._proba(features, weights)
        self.training_digest = hashlib.sha256(
            _canonical({"texts": texts, "labels": labels, "families": families})
        ).hexdigest()
        self.training_examples, self.training_families = len(texts), len(family_names)
        return {
            "optimizer_steps": steps,
            "examples_seen": steps * len(texts),
            "trainable_params": self.trainable_params,
            "parameter_bytes": self.parameter_bytes,
            "vocabulary_items": len(self.vocabulary),
            "initial_loss": initial_loss,
            "final_loss": float(
                -np.sum(
                    sample_weights
                    * np.log(np.maximum(final[np.arange(len(texts)), targets], 1e-300))
                )
            ),
            "training_accuracy": float(np.mean(final.argmax(axis=1) == targets)),
            "training_accuracy_kind": "raw_classifier_training_accuracy_including_reject_class",
            "seconds": time.perf_counter() - started,
            "training_digest": self.training_digest,
            "calibrated": False,
            "estimated_training_matmul_flops": (4 * steps + 2)
            * len(texts)
            * self.trainable_params,
        }

    def route(self, requests, mode="learned"):
        if mode not in ("typed", "literal", "learned"):
            raise ValueError("mode must be typed, literal or learned")
        if not isinstance(requests, (list, tuple)) or len(requests) > 65536:
            raise ValueError("requests must be a bounded list or tuple")
        if mode == "learned" and self.training_digest is None:
            raise ValueError("learned router has not been trained")
        result = []
        for request in requests:
            if (
                not isinstance(request, RouteRequest)
                or not isinstance(request.text, str)
                or not request.text.strip()
                or len(request.text) > 16384
            ):
                raise ValueError("invalid route request")
            candidates, issue = self._inspect(request.text)
            if _norm(request.scope) != self.scope:
                issue = "unknown_scope"
            route_id, confidence = None, None
            if issue is None and mode == "typed":
                admitted = (
                    self.types.get(_norm(request.cell_type))
                    if request.cell_type is not None
                    else None
                )
                if not admitted:
                    issue = (
                        "missing_type" if request.cell_type is None else "unknown_type"
                    )
                elif candidates and not candidates.issubset(admitted):
                    issue = "conflicting_type"
                elif len(candidates or admitted) != 1:
                    issue = "ambiguous_type"
                else:
                    route_id = next(iter(candidates or admitted))
            elif issue is None and mode == "literal":
                route_id = next(iter(candidates)) if candidates else None
                issue = None if candidates else "no_literal_address"
            elif issue is None:
                features = self._features([request.text])
                active = np.flatnonzero(features[0])
                if not len(active):
                    issue = "no_learned_evidence"
                else:
                    probabilities = self._proba(features, self.weights)[0]
                    ordered = np.argsort(probabilities)
                    winner, runner_up = int(ordered[-1]), int(ordered[-2])
                    confidence = float(probabilities[winner])
                    owners = set(self.weights[active].argmax(axis=1).tolist())
                    if len(owners) != 1:
                        issue = "ambiguous_learned_evidence"
                    elif winner == len(self.routes):
                        issue = "learned_reject"
                    elif (
                        confidence < self.threshold
                        or confidence - probabilities[runner_up] < self.margin
                    ):
                        issue = "low_confidence"
                    elif owners != {winner}:
                        issue = "unstable_learned_evidence"
                    elif candidates and self.routes[winner] not in candidates:
                        issue = "schema_model_disagreement"
                    else:
                        route_id = self.routes[winner]
            result.append(
                RoutingDecision(route_id, issue or "matched", confidence, mode)
            )
        return result

    def _weight_bytes(self):
        buffer = io.BytesIO()
        np.save(buffer, np.asarray(self.weights, dtype="<f8"), allow_pickle=False)
        return buffer.getvalue()

    def manifest(self):
        manifest = {
            "schema": "hepta.memory-cell.router.v2",
            "scope": self.scope,
            "specs": [asdict(spec) for spec in self.specs],
            "seed": self.seed,
            "threshold": self.threshold,
            "margin": self.margin,
            "feature_policy": "nfkc-casefold-binary-pure-0.8-two-families-v1",
            "vocabulary": self.vocabulary,
            "weights_shape": list(self.weights.shape),
            "weights_dtype": "float64-le",
            "weights_sha256": hashlib.sha256(self._weight_bytes()).hexdigest(),
            "training_digest": self.training_digest,
            "training_examples": self.training_examples,
            "training_families": self.training_families,
            "parameter_bytes": self.parameter_bytes,
            "trainable_params": self.trainable_params,
            "confidence_kind": "raw_softmax_not_calibrated_or_null_for_rules",
            "learned_inference_inputs": [
                "request.text",
                "request.scope_admission_only",
            ],
        }
        manifest["artifact_digest"] = hashlib.sha256(_canonical(manifest)).hexdigest()
        return json.loads(_canonical(manifest))

    def save(self, directory):
        directory = Path(directory)
        directory.mkdir(parents=True, exist_ok=False)
        manifest = self.manifest()
        (directory / "weights.npy").write_bytes(self._weight_bytes())
        (directory / "router.json").write_bytes(_canonical(manifest) + b"\n")
        return manifest

    @classmethod
    def load(cls, directory, *, expected_scope):
        directory = Path(directory)
        if (
            directory.is_symlink()
            or not directory.is_dir()
            or {path.name for path in directory.iterdir()}
            != {"router.json", "weights.npy"}
        ):
            raise ValueError("invalid router artifact inventory")
        paths = [directory / name for name in ("router.json", "weights.npy")]
        if any(
            path.is_symlink() or not path.is_file() or path.stat().st_size > 2**20
            for path in paths
        ):
            raise ValueError("invalid router artifact files")
        manifest = json.loads(
            paths[0].read_text(encoding="utf-8"), object_pairs_hook=_unique
        )
        blob = paths[1].read_bytes()
        try:
            if manifest["scope"] != _identifier(expected_scope):
                raise ValueError("router scope mismatch")
            obj = cls(
                [RouteSpec(**spec) for spec in manifest["specs"]],
                manifest["scope"],
                manifest["seed"],
                manifest["threshold"],
                manifest["margin"],
            )
            vocab = manifest["vocabulary"]
            if (
                not isinstance(vocab, list)
                or len(vocab) > 512
                or any(
                    not isinstance(token, str) or not 1 <= len(token) <= 16384
                    for token in vocab
                )
                or vocab != sorted(set(vocab))
            ):
                raise ValueError("invalid vocabulary")
            stream = io.BytesIO(blob)
            if np.lib.format.read_magic(stream) != (1, 0):
                raise ValueError("unsupported tensor encoding")
            shape, fortran, dtype = np.lib.format.read_array_header_1_0(stream)
            expected_shape = (len(vocab), len(obj.routes) + 1)
            if (
                shape != expected_shape
                or fortran
                or dtype.str != "<f8"
                or len(blob) != stream.tell() + 8 * int(np.prod(shape))
            ):
                raise ValueError("invalid tensor shape, dtype or byte count")
            obj.weights = (
                np.frombuffer(blob, dtype="<f8", offset=stream.tell())
                .copy()
                .reshape(shape)
            )
            if not np.isfinite(obj.weights).all():
                raise ValueError("nonfinite router weights")
            obj.vocabulary = tuple(vocab)
            obj.training_digest = manifest["training_digest"]
            obj.training_examples, obj.training_families = (
                manifest["training_examples"],
                manifest["training_families"],
            )
            if obj.training_digest is not None and (
                not isinstance(obj.training_digest, str)
                or re.fullmatch(r"[0-9a-f]{64}", obj.training_digest) is None
            ):
                raise ValueError("invalid training digest")
            if (
                type(obj.training_examples) is not int
                or type(obj.training_families) is not int
            ):
                raise ValueError("invalid training counters")
            if obj.training_digest is None:
                if vocab or obj.training_examples or obj.training_families:
                    raise ValueError("untrained artifact contains learned state")
            elif (
                not vocab
                or not 1 <= obj.training_examples <= 8192
                or not 2 <= obj.training_families <= 64
            ):
                raise ValueError("incomplete trained artifact")
            if obj.manifest() != manifest:
                raise ValueError("router artifact binding mismatch")
        except (KeyError, TypeError, IndexError, EOFError) as exc:
            raise ValueError("malformed router artifact") from exc
        return obj
