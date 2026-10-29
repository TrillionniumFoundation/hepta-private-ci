"""Cold OS-process continuation, exact stochastic laws, and identity refusal."""

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import subprocess
import sys

import pytest
import torch

from .checkpoint import (continuation_digest, generation_metadata, load_checkpoint,
                         save_checkpoint)
from .mechanism_data import batch
from .model import JointGenerator, tensor_digest
from .runtime import make_profile


ROOT = Path(__file__).resolve().parents[3]
MODULE = "experiments.multimodal_output_portfolio.joint_hepta_20261029.checkpoint"


def episode():
    torch.set_num_threads(1)
    torch.manual_seed(9199)
    model = JointGenerator(width=4, depth=2).eval()
    public, _ = batch([73], split="checkpoint-mechanism-test")
    profile = make_profile()
    metadata = generation_metadata(model, public, profile, source_id="synthetic-test-only",
                                   remaining_budget=98.75, generation_steps={m: 1 for m in ("image", "audio", "video", "text")})
    rng = torch.Generator(device="cpu").manual_seed(19383)
    with torch.no_grad():
        state = model.encode(public)
        model.sample(state, rng)  # Noninitial emission RNG must also survive.
        for action in ("shared", "verify"):
            state, _ = model.advance(state, action, public)
    return model, state, rng, profile, public, metadata


def test_new_os_process_resume_matches_uninterrupted_state_actions_probabilities_and_emission(tmp_path):
    model, state, rng, profile, public, metadata = episode()
    checkpoint, public_path, output = tmp_path / "state.pt", tmp_path / "public.pt", tmp_path / "cold.json"
    identity = save_checkpoint(checkpoint, model, state, rng, profile, public, metadata)
    torch.save(public, public_path)
    expected = continuation_digest(model, state, rng, public, ["image", "audio", "sample"],
                                   {**metadata, "profile": profile.to_dict()})
    result = subprocess.run([sys.executable, "-B", "-m", MODULE, "--resume", str(checkpoint),
                             "--public", str(public_path), "--actions", "image,audio,sample",
                             "--output", str(output)], cwd=ROOT, capture_output=True, text=True, timeout=120)
    assert result.returncode == 0, result.stderr
    actual = json.loads(output.read_text())
    assert actual == expected
    assert [row["requested"] for row in actual["actions"]] == ["image", "audio", "sample"]
    assert all(len(row["actor_probabilities"][0]) == 7 for row in actual["actions"])
    assert identity["state_sha256"] != actual["state_sha256"]


def test_weights_only_roundtrip_preserves_all_persistent_tensors_and_rng(tmp_path):
    model, state, rng, profile, public, metadata = episode()
    expected_global = torch.get_rng_state().clone()
    expected_episode = rng.get_state().clone()
    checkpoint = tmp_path / "state.pt"
    save_checkpoint(checkpoint, model, state, rng, profile, public, metadata)
    # The standard restricted unpickler itself can read the complete artifact.
    payload = torch.load(checkpoint, weights_only=True, map_location="cpu")
    assert payload["config"] == model.config
    assert payload["profile"] == profile.to_dict()
    assert payload["metadata"] == metadata
    torch.randn(17); torch.rand(11, generator=rng)
    restored, resumed, restored_rng, info = load_checkpoint(checkpoint, profile=profile, public=public)
    assert tensor_digest(restored.state_dict()) == tensor_digest(model.state_dict())
    assert tensor_digest(resumed.tensors()) == tensor_digest(state.tensors())
    assert torch.equal(torch.get_rng_state(), expected_global)
    assert torch.equal(restored_rng.get_state(), expected_episode)
    assert info["generation_steps"] == metadata["generation_steps"]
    assert {name: module.training for name, module in restored.named_modules()} == payload["training"]


def test_wrong_profile_or_public_input_is_rejected_before_resume(tmp_path):
    model, state, rng, profile, public, metadata = episode()
    path = tmp_path / "state.pt"
    save_checkpoint(path, model, state, rng, profile, public, metadata)
    with pytest.raises(ValueError, match="profile"):
        load_checkpoint(path, profile=make_profile("natural_context", audio_rate=512, frame_ms=500), public=public)
    changed = {key: value.clone() for key, value in public.items()}
    changed["tokens"][0, 0] += 1
    with pytest.raises(ValueError, match="Public input"):
        load_checkpoint(path, profile=profile, public=changed)


@pytest.mark.parametrize("refresh_outer_hash", [False, True])
def test_modified_tensor_fails_file_or_internal_identity(tmp_path, refresh_outer_hash):
    model, state, rng, profile, public, metadata = episode()
    path = tmp_path / "state.pt"
    save_checkpoint(path, model, state, rng, profile, public, metadata)
    payload = torch.load(path, weights_only=True, map_location="cpu")
    payload["state"]["core"][1]["adaptation"][0, 0] += .125
    torch.save(payload, path)
    if refresh_outer_hash:
        manifest = path.with_suffix(".pt.manifest.json")
        identity = json.loads(manifest.read_text())
        identity.update(file_sha256=hashlib.sha256(path.read_bytes()).hexdigest(), file_bytes=path.stat().st_size)
        manifest.write_text(json.dumps(identity))
    with pytest.raises(ValueError, match="bytes|identities"):
        load_checkpoint(path, profile=profile, public=public)


def test_mid_episode_parameter_change_cannot_be_relabelled_as_same_snapshot(tmp_path):
    model, state, rng, profile, public, metadata = episode()
    with torch.no_grad():
        model.emissions["text"].weight[0, 0] += .5
    path = tmp_path / "invalid.pt"
    with pytest.raises(ValueError, match="changed during"):
        save_checkpoint(path, model, state, rng, profile, public, metadata)
    assert not path.exists()
    with pytest.raises(ValueError, match="anchor"):
        continuation_digest(model, state, rng, public, ["image"], {**metadata, "profile": profile.to_dict()})


def test_mid_episode_missing_anchor_and_arbitrary_metadata_are_rejected(tmp_path):
    model, state, rng, profile, public, metadata = episode()
    with pytest.raises(ValueError, match="initial parameter anchor"):
        save_checkpoint(tmp_path / "unanchored.pt", model, state, rng, profile, public)
    bad = deepcopy(metadata); bad["unsafe"] = Path("unserialized-object")
    with pytest.raises(ValueError, match="unsafe"):
        save_checkpoint(tmp_path / "unsafe.pt", model, state, rng, profile, public, bad)
