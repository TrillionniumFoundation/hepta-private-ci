"""Verify actual available historical media and decode causal audio prefixes.

No downloading, pretrained inference, training, or fresh-recording claim.
"""

import argparse
import hashlib
import json
import math
from pathlib import Path
import resource
import subprocess
import time

import numpy as np
from scipy.signal import resample_poly

COHORT_SHA = "b65adcd877528b7cb5b81962ff3662c59ee1e144c26034b8a4e1d5e6426cf37a"


def sha(data):
    return hashlib.sha256(data).hexdigest()


def write(path, value):
    with path.open("x") as stream:
        json.dump(value, stream, indent=2, allow_nan=False)
        stream.write("\n")


def cpu():
    return sum(resource.getrusage(k).ru_utime + resource.getrusage(k).ru_stime
               for k in (resource.RUSAGE_SELF, resource.RUSAGE_CHILDREN))


def native_pcm(path):
    command = ["ffprobe", "-v", "error", "-show_streams", "-of", "json", str(path)]
    probe = subprocess.run(command, check=True, capture_output=True, timeout=30)
    streams = json.loads(probe.stdout)["streams"]
    audios = [s for s in streams if s["codec_type"] == "audio"]
    videos = [s for s in streams if s["codec_type"] == "video"]
    if len(audios) != 1 or len(videos) != 1 or int(audios[0]["channels"]) != 1:
        raise ValueError("Expected one native mono audio and one video stream")
    rate = int(audios[0]["sample_rate"])
    if rate != 44100:
        raise ValueError("This campaign pins native 44.1kHz input; do not silently change clocks")
    decoded = subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-xerror", "-threads", "1",
                              "-i", str(path), "-map", "0:a:0", "-ac", "1", "-threads", "1",
                              "-f", "f32le", "-"], check=True, capture_output=True, timeout=30)
    wave = np.frombuffer(decoded.stdout, dtype="<f4").copy()
    if not len(wave) or not np.isfinite(wave).all():
        raise ValueError("Empty or invalid decoded native waveform")
    return wave, rate, float(audios[0]["start_time"]), {
        "audio_codec": audios[0]["codec_name"], "video_codec": videos[0]["codec_name"],
        "video_width": int(videos[0]["width"]), "video_height": int(videos[0]["height"]),
        "video_start_seconds": float(videos[0]["start_time"])}


def accepted_resampled(wave, rate, prefix_seconds):
    # Crop the NATIVE accepted prefix first. The resampling filter never receives
    # future native samples, even when its endpoint filter needs a pad value.
    count = int(math.floor(prefix_seconds * rate))
    if len(wave) < count:
        raise ValueError("Media ends before the declared prefix; no EOF/padding substitute")
    prefix = wave[:count]
    factor = math.gcd(rate, 16000)
    result = resample_poly(prefix, 16000 // factor, rate // factor,
                           window=("kaiser", 5.0), padtype="constant").astype("<f4")
    if len(result) != int(prefix_seconds * 16000) or not np.isfinite(result).all():
        raise ValueError("Invalid resampled prefix")
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cohort", type=Path, required=True)
    parser.add_argument("--media", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=False)
    began_cpu, began_wall = cpu(), time.perf_counter()
    cohort_bytes = args.cohort.read_bytes()
    if sha(cohort_bytes) != COHORT_SHA:
        raise ValueError("Historical cohort identity differs")
    cohort = json.loads(cohort_bytes)
    declared = {r["clip"]:r for r in cohort["records"]}
    # Freeze the bytes of provenance, not a new cohort allocation.
    (args.out / "HISTORICAL_COHORT.json").write_bytes(cohort_bytes)
    records, rejections = [], []
    future_controls = []
    for path in sorted(args.media.glob("*.flv")):
        payload = path.read_bytes()
        row = declared.get(path.stem)
        if row is None or len(payload) != row["bytes"] or sha(payload) != row["sha256"]:
            rejections.append({"file":path.name,"bytes":len(payload),"sha256":sha(payload),
                               "reason":"Missing cohort identity or source byte mismatch"})
            continue
        # Existing raw data all belong to an unfinished historical TRAIN cohort.
        if row["split"] != "train":
            raise ValueError("Unexpected non-training media; do not inspect heldout inputs")
        wave, rate, start, streams = native_pcm(path)
        prefixes = []
        for seconds in (1.,2.,3.):
            if len(wave) < int(seconds*rate):
                prefixes.append({"seconds":seconds,"available":False,
                                 "reason":"source shorter than declared prefix; rejected without padding"})
                continue
            values = accepted_resampled(wave,rate,seconds)
            prefixes.append({"seconds":seconds,"available":True,"sample_count":len(values),
                             "float32_sha256":sha(values.tobytes()),
                             "native_accepted_samples":int(seconds*rate)})
            if not future_controls and len(wave)>int(seconds*rate):
                changed=wave.copy()
                changed[int(seconds*rate):]=np.nan
                repeated=accepted_resampled(changed,rate,seconds)
                if not np.array_equal(values,repeated):
                    raise AssertionError("Future native samples changed accepted prefix")
                future_controls.append({"clip":row["clip"],"seconds":seconds,
                                        "future_nan_prefix_bitwise_equal":True})
                np.savez_compressed(args.out/"ACTUAL_PREFIX_SAMPLE.npz",waveform=values,
                                    sample_rate=np.array(16000),native_rate=np.array(rate),
                                    source_sha256=np.array(row["sha256"]),
                                    recording_id=np.array(row["clip"]),prefix_seconds=np.array(seconds))
        records.append({**row,"native_sample_rate":rate,"native_sample_count":len(wave),
                        "native_pcm_float32_sha256":sha(wave.tobytes()),"audio_start_seconds":start,
                        "streams":streams,"prefixes":prefixes})
    source_sha=sha(Path(__file__).read_bytes())
    result={"schema":"hcsn-v12-existing-raw-media-availability.v1","source_sha256":source_sha,
            "cohort_sha256":COHORT_SHA,"upstream_sha":cohort["upstream_sha"],
            "media_directory":str(args.media),"verified_media":records,"rejected_paths":rejections,
            "existing_media_count":len(records),"actors":sorted({r['actor'] for r in records}),
            "all_existing_media_are_historical_training":True,"fresh_confirmation":False,
            "future_sample_controls":future_controls,"strong_audio_inference_completed":False,
            "external_v6_full_exclusions_recovered":False,"production_activation":False,
            "cpu_seconds_self_plus_waited_children":cpu()-began_cpu,
            "wall_seconds":time.perf_counter()-began_wall,
            "cost_scope":"Task process plus waited ffprobe/ffmpeg, excluding startup/import and report final serialization; outer worker receipt is complete enclosing CPU and contains this once."}
    write(args.out/"AVAILABILITY.json",result)
    print(json.dumps({"verified_media":len(records),"rejected_paths":len(rejections),
                      "actors":result['actors'],"future_controls":len(future_controls)}))


if __name__=="__main__":
    main()
