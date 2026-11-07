"""Bounded JSON adapter for an actual research Cell job, without self-authentication."""

import argparse
import json
from pathlib import Path

from ndu_real_materials.common import strict_json
from .episode import EpisodeHost, write_bytes_once
from .metering import atomic_json, file_sha


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("source", "weights", "input", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--operation-id", required=True)
    args = parser.parse_args()
    raw = args.input.read_bytes()
    if len(raw) > 65536:
        raise ValueError("Native job input exceeds the owner bound")
    request = strict_json(raw)
    actor_source = Path(request["config"]["scripts_root"]) / "ndu_real_runtime/actor.py"
    if file_sha(actor_source) != file_sha(args.source):
        raise ValueError("Native fixed source copy does not bind the actual deployed actor bytes")
    for binding in request["code_pins"]:
        if file_sha(binding["path"]) != binding["sha256"]:
            raise ValueError("Actual deployed code differs from the frozen source inventory")
    if file_sha(args.weights) != request["profile"]["model_sha256"]:
        raise ValueError("Actual native weights differ from the pinned model")
    request["profile"]["weights"] = str(args.weights)
    request["profile"]["original_operation_id"] = args.operation_id
    result = EpisodeHost(request["config"], request["case"], request["profile"], request["output"]).run()
    if result["terminal_status"] == "Failed":
        raise RuntimeError("Actual native inference failed; original episode evidence retained")
    directory = Path(request["output"])
    deliveries = sorted(directory.glob("delivery-*/delivery.json"))
    delivery = strict_json(deliveries[-1].read_bytes())
    text_path = directory / "native-text.txt"
    write_bytes_once(text_path, (delivery["text"] or "").encode())
    output = {"schema": "ndu.real.native-worker-result.v1", "original_operation_id": args.operation_id,
              "model_sha256": file_sha(args.weights), "source_sha256": file_sha(args.source),
              "output_text_path": str(text_path), "output_text_sha256": file_sha(text_path),
              "text_present": delivery["text"] is not None,
              "episode_result_path": str(directory / "result.json"),
              "episode_result_sha256": file_sha(directory / "result.json"),
              "terminal_status": result["terminal_status"], "formal_final_use_claim": False}
    if delivery["image"] is not None:
        path = deliveries[-1].parent / delivery["image"]["path"]
        output.update(output_image_path=str(path), output_image_sha256=file_sha(path))
    for binding in request["code_pins"]:
        if file_sha(binding["path"]) != binding["sha256"]:
            raise ValueError("Deployed source changed during native inference")
    atomic_json(args.output, output)
    print(json.dumps(output, sort_keys=True), flush=True)
    return 0
