"""Bounded acquisition of the official pretrained audio checkpoint, outside Git."""

import argparse
import hashlib
import json
from pathlib import Path
import time
import urllib.request


HERE = Path(__file__).resolve().parent
URL = "https://download.pytorch.org/torchaudio/models/wav2vec2_fairseq_base_ls960_asr_ls960.pth"
MAX_BYTES = 512 * 1024**2


def digest(path):
    value = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b""):
            value.update(chunk)
    return value.hexdigest()


def run(directory):
    directory.mkdir(parents=True, exist_ok=True)
    checkpoint = directory / URL.rsplit("/", 1)[1]
    partial = checkpoint.with_suffix(checkpoint.suffix + ".partial")
    if checkpoint.exists() or partial.exists() or (HERE / "CHECKPOINT.json").exists():
        raise FileExistsError("Acquisition refuses existing output")
    cpu, wall = time.process_time(), time.perf_counter()
    received = 0
    try:
        with urllib.request.urlopen(URL, timeout=60) as response, partial.open("xb") as stream:
            if response.status != 200:
                raise ValueError("Official checkpoint did not return HTTP200")
            announced = response.headers.get("Content-Length")
            if announced is not None and not 0 < int(announced) <= MAX_BYTES:
                raise ValueError("Checkpoint size exceeds declared acquisition cap")
            while block := response.read(1 << 20):
                received += len(block)
                if received > MAX_BYTES:
                    raise ValueError("Checkpoint size exceeds declared acquisition cap")
                stream.write(block)
            if announced is not None and received != int(announced):
                raise ValueError("Truncated checkpoint")
        partial.replace(checkpoint)
        result = dict(schema="hcsn.audio.pretrained.checkpoint.v1", url=URL,
            path=str(checkpoint.resolve()), bytes=received, sha256=digest(checkpoint),
            official_bundle="torchaudio.pipelines.WAV2VEC2_ASR_BASE_960H",
            torchaudio_version="2.6.0+cpu", torch_version="2.6.0+cpu",
            upstream_audio_commit="d8831425203385077a03c1d92cfbbe3bf2106008",
            upstream_bundle_blob="d60fa8adb94e92e1a479fe94e09f521d0fe50056",
            upstream_utility_blob="e690e8103c7a47a01d719e746e6c98a9c7f6c8db",
            model_documentation="https://docs.pytorch.org/audio/2.6.0/generated/torchaudio.pipelines.WAV2VEC2_ASR_BASE_960H.html",
            weight_license="MIT; official model documentation explicitly licenses redistributed weights",
            license_notice="https://github.com/facebookresearch/fairseq/blob/ce6c9eeae163ac04b79539c78e74f292f29eaa18/LICENSE",
            software_license="TorchAudio BSD-2-Clause, distinct from model-weight MIT",
            pretraining_data="LibriSpeech train-clean-100 + train-clean-360 + train-other-500, 960h audio",
            asr_finetuning_data="The same LibriSpeech960h audio with corresponding transcripts",
            checkpoint_publicly_republished=False, included_in_source_bundle=False,
            download_body_cpu_seconds=time.process_time()-cpu, download_wall_seconds=time.perf_counter()-wall,
            actual_sha256_first_observed_here=True)
        with (HERE / "CHECKPOINT.json").open("x") as stream:
            json.dump(result, stream, indent=2); stream.write("\n")
        print(json.dumps({k: result[k] for k in ("bytes", "sha256", "download_wall_seconds")}))
    except Exception as error:
        failure = dict(status="failed", error=repr(error), received_bytes=received, url=URL,
                       partial_path=str(partial), partial_sha256=digest(partial) if partial.exists() else None,
                       cpu_seconds=time.process_time()-cpu, wall_seconds=time.perf_counter()-wall)
        with (HERE / "ACQUISITION_FAILURE.json").open("x") as stream:
            json.dump(failure, stream, indent=2); stream.write("\n")
        raise


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--directory", type=Path, required=True)
    run(parser.parse_args().directory)
