"""Research-only current source checks around an actually loaded procedure Head.

The host withdrawal view is a controlled experiment input, not a signed runtime
ledger. Withdrawal invalidates use; it does not delete learned parameter influence.
"""

from dataclasses import asdict
import json
from pathlib import Path
import re

from cell_evolution_snapshot import check_sources
from cell_head_training import load_head_artifact
from feature_bundle import FeatureBundleV1
from procedure_replay_contracts import sha


class ReplayHeadOwner:
    def __init__(self, directory, expected_owner_manifest_sha256, identity, provider):
        path = Path(directory) / "replay_owner.json"
        if path.is_symlink() or not path.is_file() or path.stat().st_size > 1048576:
            raise ValueError("bounded real owner manifest required")
        raw = path.read_bytes()
        if sha(raw) != expected_owner_manifest_sha256:
            raise ValueError("owner manifest differs from independently retained pin")
        manifest = json.loads(raw)
        self.sources = tuple(manifest["learned_source_digests"])
        if (manifest["feature_identity"] != asdict(identity)
                or manifest["authority"] != "DENY_ALL" or manifest["mode"] != "SHADOW_ONLY"
                or not self.sources or len(self.sources) > 16384
                or self.sources != tuple(sorted(set(self.sources)))
                or any(re.fullmatch("[0-9a-f]{64}", value) is None for value in self.sources)):
            raise ValueError("invalid owner source closure or identity")
        self.provider = provider
        self.identity = identity
        self.minimum = asdict(check_sources(self.sources, identity, provider))
        self.model = load_head_artifact(directory, expected_manifest_sha256=manifest["head_manifest_sha256"],
                                        expected_identity=identity)
        self.forward_calls = 0
        self.example_calls = 0
        self.invalidated = False
        self._handle = self.model._head.register_forward_hook(self._observe_forward)

    def _observe_forward(self, module, arguments, result):
        self.forward_calls += 1
        self.example_calls += len(arguments[0])

    def predict(self, bundle):
        if self.invalidated:
            raise ValueError("owner instance was invalidated; host frontier rollback cannot restore it")
        if type(bundle) is not FeatureBundleV1 or bundle.identity != self.identity:
            raise ValueError("matching real feature bundle required")
        sources = tuple(sorted(set(self.sources) | set(bundle.source_record_digests)))
        try:
            before = check_sources(sources, self.identity, self.provider, self.minimum)
        except ValueError:
            self.invalidated = True
            raise
        result = self.model.predict_task(bundle)
        try:
            after = check_sources(sources, self.identity, self.provider, asdict(before))
            if before != after:
                raise ValueError("withdrawal view changed during prediction")
        except ValueError:
            self.invalidated = True
            raise
        self.minimum = asdict(after)
        return result
