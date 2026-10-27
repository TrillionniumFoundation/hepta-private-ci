"""Reject stale value models before changing a live original-owner session."""

import argparse
import json
from pathlib import Path
import shutil

from ...continuation_20261027.control.client import Native
from ...continuation_20261027.control.training import prefix
from .binding import BoundCritic
from .protocol import digest, sha, write


def tree_identity(directory):
    return {str(path.relative_to(directory)): sha(path) for path in directory.rglob("*") if path.is_file()}


def run(development, generator_path, binary, output):
    output.mkdir(parents=True, exist_ok=False)
    copied = output / "frozen-copy"
    copied.mkdir()
    for name in ("FROZEN.json", "MODEL.json", "READOUT_FIT.json", "FIT.json", "CRITIC_SELECTION.json", "PROTOCOL.json", "ENCODER_DOMAIN_PROOF.json"):
        shutil.copyfile(development / name, copied / name)
    (copied / "executed-source").mkdir()
    for name in ("adapter.py", "critic.py"):
        shutil.copyfile(development / "executed-source" / name, copied / "executed-source" / name)
    critic = BoundCritic(copied, generator_path, binary)
    accepted = critic.predict("clean", "native_numeric", 7, 2)
    native = Native(binary)
    native.open(output / "owner", "semantic-version-binding-check", 7, copied / "MODEL.json", copied / "ENCODER_DOMAIN_PROOF.json")
    prefix(native, 0)
    before = native.call({"command": "Status"})
    before_bytes = tree_identity(output / "owner")
    failures = []

    def reject(label, change, undo):
        change()
        try:
            critic.predict("clean", "native_numeric", 7, 2)
        except ValueError as error:
            failures.append({"case": label, "rejection": str(error)})
        else:
            raise AssertionError("A stale runtime was allowed to use the critic")
        finally:
            undo()
        if native.call({"command": "Status"}) != before or tree_identity(output / "owner") != before_bytes:
            raise AssertionError("Rejected model version advanced original owner state")

    wrong = output / "different-generator.pt"
    wrong.write_bytes(b"a distinct generation distribution requiring new fitting and validation")
    reject("different_generator_checkpoint", lambda: setattr(critic, "generator_path", wrong),
           lambda: setattr(critic, "generator_path", generator_path))
    reject("different_owner_runtime", lambda: setattr(critic, "binary_path", wrong),
           lambda: setattr(critic, "binary_path", binary))
    for name in ("MODEL.json", "READOUT_FIT.json", "ENCODER_DOMAIN_PROOF.json", "FIT.json", "CRITIC_SELECTION.json", "PROTOCOL.json"):
        target = copied / name
        original = target.read_bytes()
        reject("changed_" + name, lambda p=target, data=original: p.write_bytes(data + b"\n"),
               lambda p=target, data=original: p.write_bytes(data))
    if critic.predict("clean", "native_numeric", 7, 2) != accepted:
        raise AssertionError("Restoring the exact bound runtime changed the estimate")
    native.close()
    write(output / "TRANSCRIPT.json", native.transcript)
    native.finish()
    write(output / "RESULT.json", {"passed": True, "rejected_versions": failures,
        "state_and_durable_bytes_unchanged_after_every_rejection": True, "bound_runtime_sha256": critic.fingerprint,
        "bound_runtime_identity": critic.expected, "restored_prediction_identity": digest(accepted),
        "new_test_sources_or_outputs_used": False, "qualification_rerun": False,
        "timing": "Post-qualification-start interface hardening; original qualification source snapshot unchanged"})
    print(json.dumps({"passed": True, "rejections": len(failures), "bound_runtime_sha256": critic.fingerprint}), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    for name in ("development", "generator", "binary", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args()
    run(args.development, args.generator, args.binary, args.output)
