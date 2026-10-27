"""A critic is executable only with its exact generator and continuation.

This guard was added after the first semantic qualification started. That run
already checked fixed checkpoint identities at entry; its original executed
source remains sealed. This reusable interface additionally refuses changed
runtime artifacts before every future prediction.
"""

import ast
import hashlib
import json
from pathlib import Path

from .critic import predict
from .protocol import PROTOCOL as P, digest, sha


DECODER_DEPENDENCIES = (
    "v6/data.py", "v6/neural.py", "v6/conditioned.py", "v6/plan_training.py",
    "v6/observer.py", "repair_20261026/joint/train.py",
)
BASELINE_DECODER_SHA256 = {
    "v6/data.py": "de749eedcbffb7525b97c40a3721e3888a157e020333f43c55aa55db0784ef29",
    "v6/neural.py": "6447edf81da45695ab87a033c544ff7c554a15431e614474be7ad3b7c329e742",
    "v6/conditioned.py": "ccb5f9a78e58d6f1d1511a95f50de3602e1f39e7254fce5566e97a994d5b4cba",
    "v6/plan_training.py": "b43ff714960139d4b58d02dec86b69d27ac51d5abfd75509936ee2c5c355997b",
    "v6/observer.py": "5e9c6444e43ae3ccd44b1683a94f6d6487d8956534e4bfc6c2fcfa069bbf716e",
    "repair_20261026/joint/train.py": "71776941c8c7d289b6c3ad2886cfab3512f2ae7b3ffd3898fda6c5a2a72c9c8c",
}
CALIBRATION_SHA256 = "8de3536b03f2fa2b6475b64635dbbd3345279a867cf82cf770fee495dc59c929"


def ast_hash(source):
    return hashlib.sha256(ast.dump(ast.parse(source), include_attributes=False).encode()).hexdigest()


def delivery_ast(source):
    tree = ast.parse(source)
    node = next(item for item in tree.body if isinstance(item, ast.ClassDef) and item.name == "Generator")
    method = next(item for item in node.body if isinstance(item, ast.FunctionDef) and item.name == "deliver")
    return hashlib.sha256(ast.dump(method, include_attributes=False).encode()).hexdigest()


def decoder_contract(adapter_source=None):
    root = Path(__file__).resolve().parents[2]
    adapter = Path(__file__).with_name("adapter.py")
    return {"name": "public-observation-order-command-two-transitions-greedy-png-utf8.v1",
        "delivery_function_ast_sha256": delivery_ast(adapter_source if adapter_source is not None else adapter.read_text()),
        "dependency_file_sha256": (BASELINE_DECODER_SHA256 if adapter_source is not None else
            {name: sha(root / name) for name in DECODER_DEPENDENCIES})}


class BoundCritic:
    """Load frozen evidence, then read actual runtime files to enforce identity."""

    def __init__(self, development, generator_path, binary_path):
        self.development = Path(development)
        self.generator_path, self.binary_path = Path(generator_path), Path(binary_path)
        frozen = json.loads((self.development / "FROZEN.json").read_text())
        adapter_source = self.development / "executed-source/adapter.py"
        if sha(adapter_source) != frozen["source_sha256"]["adapter.py"]:
            raise ValueError("Frozen decoder adapter identity differs")
        critic_source = self.development / "executed-source/critic.py"
        if sha(critic_source) != frozen["source_sha256"]["critic.py"]:
            raise ValueError("Frozen empirical-law algorithm differs")
        self.expected = {
            "generator_checkpoint_sha256": frozen["generator_sha256"],
            "owner_binary_sha256": frozen["binary_sha256"],
            "owner_readout_sha256": frozen["model_sha256"],
            "decoder_contract": decoder_contract(adapter_source.read_text()),
            "policy_protocol_sha256": frozen["protocol_sha256"],
            "readout_heads_sha256": frozen["readout_fit_sha256"],
            "empirical_joint_law_sha256": frozen["fit_sha256"],
            "pooling_choice_sha256": frozen["critic_selection_sha256"],
            "owner_calibration_sha256": CALIBRATION_SHA256,
            "critic_algorithm_ast_sha256": ast_hash(critic_source.read_text()),
        }
        self.fingerprint = digest(self.expected)
        self.verify()
        if json.loads((self.development / "PROTOCOL.json").read_text()) != P:
            raise ValueError("This continuation policy requires refitting for a changed protocol")
        self._fit = json.loads((self.development / "FIT.json").read_text())
        self._heads = json.loads((self.development / "READOUT_FIT.json").read_text())
        self._shrinkage = json.loads((self.development / "CRITIC_SELECTION.json").read_text())["selected_shrinkage"]

    def verify(self):
        actual = {
            "generator_checkpoint_sha256": sha(self.generator_path),
            "owner_binary_sha256": sha(self.binary_path),
            "owner_readout_sha256": sha(self.development / "MODEL.json"),
            "decoder_contract": decoder_contract(),
            "policy_protocol_sha256": sha(self.development / "PROTOCOL.json"),
            "readout_heads_sha256": sha(self.development / "READOUT_FIT.json"),
            "empirical_joint_law_sha256": sha(self.development / "FIT.json"),
            "pooling_choice_sha256": sha(self.development / "CRITIC_SELECTION.json"),
            "owner_calibration_sha256": sha(self.development / "ENCODER_DOMAIN_PROOF.json"),
            "critic_algorithm_ast_sha256": ast_hash(Path(__file__).with_name("critic.py").read_text()),
        }
        if actual != self.expected:
            raise ValueError("Critic/runtime identity mismatch: refit and validate before predicting")
        return self.fingerprint

    def predict(self, condition, arm, expires, budget, feedback=None):
        self.verify()
        result = predict(self._fit, condition, arm, expires, budget, self._heads, self._shrinkage, feedback)
        return {**result, "bound_runtime_sha256": self.fingerprint}

    def verify_inputs(self, fit, heads, shrinkage):
        self.verify()
        if digest(fit) != digest(self._fit) or digest(heads) != digest(self._heads) or shrinkage != self._shrinkage:
            raise ValueError("Caller supplied a law or policy different from the bound continuation")
