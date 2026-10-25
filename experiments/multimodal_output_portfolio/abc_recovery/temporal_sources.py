"""Register and retain small official GRID sources without any task evaluation.

Only ZIP directories are read before all speaker/clip identities are frozen.
Format decoding and timestamp inventories are not semantic or lip-sync scores.
"""

import argparse
from datetime import datetime, timezone
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import resource
import shutil
import subprocess
import time
import traceback
from urllib.request import Request, urlopen
import zipfile
import zlib


def digest(value):
    return hashlib.sha256(value).hexdigest()


def stamp():
    return datetime.now(timezone.utc).isoformat()


def save(path, content):
    with Path(path).open("xb") as stream:
        stream.write(content)
        stream.flush()
        os.fsync(stream.fileno())
    return digest(content)


def save_json(path, value):
    return save(path, (json.dumps(value, indent=2, sort_keys=True) + "\n").encode())


def usage():
    own, children = resource.getrusage(resource.RUSAGE_SELF), resource.getrusage(resource.RUSAGE_CHILDREN)
    return {"wall_seconds": time.monotonic(), "cpu_seconds": own.ru_utime + own.ru_stime,
            "child_cpu_seconds": children.ru_utime + children.ru_stime,
            "maximum_rss_bytes": max(own.ru_maxrss, children.ru_maxrss) * 1024}


def elapsed(start):
    now = usage()
    return {key: value if key == "maximum_rss_bytes" else value - start[key] for key, value in now.items()}


def ledger(path, row):
    with Path(path).open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(row, sort_keys=True) + "\n")
        stream.flush()
        os.fsync(stream.fileno())


class RangeReader(io.RawIOBase):
    """Seekable, bounded HTTPS ZIP reader retaining every response and receipt."""

    def __init__(self, meta, output, budget, transport=urlopen):
        self.meta, self.output, self.budget, self.transport = meta, Path(output), budget, transport
        self.url, self.size = meta["links"]["self"], meta["size"]
        self.position, self.etag, self.phase = 0, None, "zip_directory"

    def readable(self):
        return True

    def seekable(self):
        return True

    def tell(self):
        return self.position

    def seek(self, offset, whence=0):
        position = offset + (self.position if whence == 1 else self.size if whence == 2 else 0)
        if whence not in (0, 1, 2) or not 0 <= position <= self.size:
            raise ValueError("Invalid ZIP seek")
        self.position = position
        return position

    def read(self, count=-1):
        count = self.size - self.position if count < 0 else min(count, self.size - self.position)
        if count == 0:
            return b""
        limits = self.budget["limits"]
        if count > limits["maximum_range_bytes"]:
            raise ValueError("Range exceeds the prospective byte limit")
        if self.budget["transferred_bytes"] + count > limits["maximum_total_transferred_bytes"]:
            raise ValueError("Source retrieval exceeds the prospective total byte limit")
        first, last = self.position, self.position + count - 1
        request = Request(self.url, headers={"Range": f"bytes={first}-{last}", "Accept-Encoding": "identity"})
        self.budget["requests"] += 1
        number = self.budget["requests"]
        before = usage()
        row = {"request_id": number, "archive": self.meta["key"], "phase": self.phase,
               "url": self.url, "requested_range": [first, last], "at_utc": stamp()}
        try:
            with self.transport(request, timeout=45) as response:
                body = response.read(count + 1)
                self.budget["transferred_bytes"] += len(body)
                row.update(status=response.status, content_range=response.headers.get("Content-Range"),
                           etag=response.headers.get("ETag"), last_modified=response.headers.get("Last-Modified"),
                           bytes=len(body), sha256=digest(body), final_url=response.geturl())
                filename = f"ranges/{number:05d}-{self.meta['key']}-{first}-{last}.bin"
                save(self.output / filename, body)
                row["retained_response"] = filename
                expected = f"bytes {first}-{last}/{self.size}"
                if response.status != 206 or row["content_range"] != expected or len(body) != count:
                    raise ValueError(f"Range response mismatch: {self.meta['key']} {row['content_range']}")
                if self.etag and row["etag"] != self.etag:
                    raise ValueError("Official archive ETag changed during partial retrieval")
                self.etag = row["etag"] or self.etag
                self.position += count
                return body
        except BaseException as error:
            row["error"] = f"{type(error).__name__}: {error}"
            raise
        finally:
            row["cost"] = elapsed(before)
            ledger(self.output / "range-requests.jsonl", row)


def entry(info):
    return {"member": info.filename, "crc32": f"{info.CRC:08x}", "bytes": info.file_size,
            "compressed_bytes": info.compress_size, "compression_type": info.compress_type,
            "local_header_offset": info.header_offset, "flag_bits": info.flag_bits}


def eligible(info, speaker, suffix):
    path = PurePosixPath(info.filename)
    return (not info.is_dir() and path.suffix.lower() == suffix and f"s{speaker}" in path.parts[:-1]
            and "__MACOSX" not in path.parts and not path.name.startswith(".") and ".." not in path.parts)


def pick_clip(infos, speaker):
    candidates = [info for info in infos if eligible(info, speaker, ".mpg")]
    if not candidates:
        raise ValueError(f"No registered-format video member for speaker {speaker}")
    key = lambda info: (digest(f"hepta-temporal-clip-v1|s{speaker}|{info.filename}".encode()), info.filename)
    return min(candidates, key=key), len(candidates)


def freeze_selection(output, protocol_sha, record_sha, choices, budget):
    """Freeze every member identity before any selected member can be read."""
    path = Path(output) / "selected-source-manifest.json"
    selected = {"schema": "hepta.ndu-abc.grid-selected-sources.v1", "frozen_at_utc": stamp(),
                "protocol_sha256": protocol_sha, "official_metadata_sha256": record_sha,
                "source_amendment_sha256": budget.get("source_amendment_sha256"),
                "candidate_universes_sha256": budget.get("candidate_universes_sha256"),
                "selection_uses_only_zip_directory_names": True, "task_outcomes_opened": False,
                "source_groups": choices, "independent_group_count": len(choices),
                "metadata_requests_before_freeze": budget["requests"],
                "metadata_transferred_bytes_before_freeze": budget["transferred_bytes"]}
    budget["selection_sha256"] = save_json(path, selected)
    return selected


def read_member(archive, reader, registered, destination):
    frozen = reader.output / "selected-source-manifest.json"
    if not frozen.is_file() or digest(frozen.read_bytes()) != reader.budget.get("selection_sha256"):
        raise ValueError("All selected sources must be frozen unchanged before member reads")
    info = archive.getinfo(registered["member"])
    if entry(info) != registered:
        raise ValueError("ZIP member identity differs from the frozen selection")
    limits = reader.budget["limits"]
    if (info.file_size > limits["maximum_member_bytes"]
            or info.compress_size > limits["maximum_member_compressed_bytes"]):
        raise ValueError("Selected member exceeds the prospective size limit; substitution prohibited")
    reader.phase = "selected_member_payload"
    first_request = reader.budget["requests"] + 1
    with archive.open(info) as stream:
        body = stream.read(info.file_size + 1)
    if len(body) != info.file_size or zlib.crc32(body) != info.CRC:
        raise ValueError("Selected member size or CRC mismatch")
    return {**registered, "sha256": save(destination, body),
            "retained_original": str(Path(destination).relative_to(reader.output)),
            "request_id_interval": [first_request, reader.budget["requests"]],
            "zip_member_crc32_verified": True, "whole_archive_md5_verified": False}


def run_format_command(command, prefix):
    before = usage()
    row = {"argv": command, "at_utc": stamp()}
    try:
        result = subprocess.run(command, capture_output=True, timeout=45, check=False)
        row.update(returncode=result.returncode, stdout_sha256=save(prefix.with_suffix(".stdout"), result.stdout),
                   stderr_sha256=save(prefix.with_suffix(".stderr"), result.stderr))
        if result.returncode:
            raise RuntimeError(f"Format inventory command failed ({result.returncode})")
        return result.stdout
    except BaseException as error:
        row["error"] = f"{type(error).__name__}: {error}"
        raise
    finally:
        row["cost"] = elapsed(before)
        save_json(prefix.with_suffix(".receipt.json"), row)


def alignment_rows(path):
    result, previous = [], 0
    for line in Path(path).read_text().splitlines():
        fields = line.split()
        if len(fields) != 3:
            raise ValueError("Unexpected original word alignment format")
        start, end = map(int, fields[:2])
        if start < previous or end < start:
            raise ValueError("Non-monotone original acoustic word boundaries")
        result.append({"start_raw": start, "end_raw": end, "word": fields[2]})
        previous = end
    return {"raw_rows": result, "timebase_documented": False,
            "candidate_units_not_adopted": ["25000 sample ticks / second", "10000000 HTK ticks / second"],
            "independent_lip_motion_ground_truth": False}


def inspect_original(path, output, tools):
    probe = run_format_command([tools["ffprobe"], "-v", "error", "-protocol_whitelist", "file,pipe",
                                "-show_format", "-show_streams", "-show_frames", "-of", "json", str(path)],
                               output / "ffprobe")
    parsed = json.loads(probe)
    frames = parsed.get("frames", [])
    clocks = {}
    for kind in ("video", "audio"):
        selected = [frame for frame in frames if frame.get("media_type") == kind]
        clocks[kind] = {"decoded_frame_count": len(selected),
                        "pts_seconds": [frame.get("pts_time", frame.get("best_effort_timestamp_time"))
                                        for frame in selected],
                        "duration_seconds": [frame.get("pkt_duration_time") for frame in selected],
                        "sample_count": sum(frame.get("nb_samples", 0) for frame in selected)}
    if not all(value["decoded_frame_count"] for value in clocks.values()):
        raise ValueError("Selected original lacks a decodable required audio or video stream")
    run_format_command([tools["ffmpeg"], "-nostdin", "-v", "error", "-protocol_whitelist", "file,pipe",
                        "-i", str(path), "-map", "0:v:0", "-map", "0:a:0", "-f", "null", "-"],
                       output / "ffmpeg")
    return {"streams": parsed["streams"], "format": parsed.get("format"), "actual_clocks": clocks,
            "format_decoding_passed": True, "lip_synchronization_scored": False,
            "nominal_frame_rate_used_as_ground_truth": False}


def validate_roles(protocol):
    selection = protocol["source_selection"]
    order = sorted([i for i in range(1, 35) if i not in (2, 21, 23)],
                   key=lambda i: (digest(f"hepta-temporal-speaker-v1|s{i}".encode()), i))
    expected = {"fit": order[:10], "calibration": order[10:15], "evaluation": order[15:]}
    if selection["roles"] != expected or selection["excluded_speakers"] != [2, 21, 23]:
        raise ValueError("Speaker allocation differs from the approved source registration")
    return expected


def prepare(protocol_path, metadata_path, output, amendment_path=None, mapping_evidence=None):
    before, output = usage(), Path(output)
    output.mkdir(parents=True, exist_ok=False)
    (output / "ranges").mkdir()
    open_archives, budget = {}, None
    try:
        protocol_bytes, metadata_bytes = Path(protocol_path).read_bytes(), Path(metadata_path).read_bytes()
        protocol, record = json.loads(protocol_bytes), json.loads(metadata_bytes)
        roles = validate_roles(protocol)
        amendment, mapping = None, {str(speaker): speaker for values in roles.values() for speaker in values}
        if amendment_path:
            from .temporal_source_repair import verified_mapping, verify_author_source
            amendment = json.loads(Path(amendment_path).read_bytes())
            mapping = verified_mapping(amendment, mapping_evidence, digest(protocol_bytes))
        if digest(metadata_bytes) != protocol["source_dataset"]["metadata_file_sha256"]:
            raise ValueError("Author-deposited source metadata differs from the registered exact bytes")
        if record["metadata"]["license"]["id"] != "cc-by-4.0":
            raise ValueError("Unexpected official source license")
        tools = {name: shutil.which(name) for name in ("ffprobe", "ffmpeg")}
        if not all(tools.values()):
            raise ValueError("Required media format tools are unavailable")
        budget = {"limits": protocol["download"], "transferred_bytes": 0, "requests": 0}
        registration = {"at_utc": stamp(), "protocol_sha256": save(output / "protocol.json", protocol_bytes),
                        "official_metadata_sha256": save(output / "official-record.json", metadata_bytes),
                        "source_code_sha256": save(output / "temporal_sources.py", Path(__file__).read_bytes()),
                        "format_tools": {key: {"path": value, "binary_sha256": digest(Path(value).read_bytes())}
                                         for key, value in tools.items()},
                        "task_outcomes_authorized": False, "retained_members_require_selection_freeze": True}
        if amendment:
            registration["source_amendment_sha256"] = save(output / "source-amendment.json", Path(amendment_path).read_bytes())
            budget["source_amendment_sha256"] = registration["source_amendment_sha256"]
            registration["repair_implementation_sha256"] = save(output / "temporal_source_repair.py", Path(__file__).with_name("temporal_source_repair.py").read_bytes())
            save(output / "pinned-maintainer-grid.py", Path(mapping_evidence).read_bytes())
        save_json(output / "preparation-registration.json", registration)
        by_name = {item["key"]: item for item in record["files"]}
        names = ["alignments.zip"] + [f"s{i}.zip" for members in roles.values() for i in members]
        for name in names:
            meta = by_name[name]
            if not meta["links"]["self"].startswith("https://zenodo.org/api/records/3625687/files/"):
                raise ValueError("Source URL is outside the registered official archive")
            reader = RangeReader(meta, output, budget)
            archive = zipfile.ZipFile(reader)
            open_archives[name] = (archive, reader)
            save_json(output / f"{name}.directory.json", [entry(info) for info in archive.infolist()])
            print(f"directory {len(open_archives)}/{len(names)} {name} entries={len(archive.infolist())}", flush=True)
        choices, universes = [], {}
        alignments = open_archives["alignments.zip"][0].infolist()
        for role, speakers in roles.items():
            for speaker in speakers:
                name = f"s{speaker}.zip"
                chosen, count = pick_clip(open_archives[name][0].infolist(), speaker)
                raw_speaker = mapping[str(speaker)]
                matching_group = [info for info in alignments if eligible(info, raw_speaker, ".align")]
                video_group = [info for info in open_archives[name][0].infolist() if eligible(info, speaker, ".mpg")]
                video_stems = sorted(PurePosixPath(info.filename).stem for info in video_group)
                if amendment and video_stems != sorted(PurePosixPath(info.filename).stem for info in matching_group):
                    raise ValueError("Corrected annotation universe differs from the fixed video universe")
                universes[str(speaker)] = video_stems
                matches = [info for info in matching_group
                           if PurePosixPath(info.filename).stem == PurePosixPath(chosen.filename).stem]
                if len(matches) != 1:
                    raise ValueError(f"Selected source s{speaker}/{chosen.filename} has {len(matches)} alignments")
                choices.append({"speaker": speaker, "role": role,
                                "raw_alignment_speaker": raw_speaker,
                                "source_id": f"grid:s{speaker}:{PurePosixPath(chosen.filename).stem}",
                                "eligible_clip_count": count, "archive": name,
                                "published_archive_checksum_unverified": by_name[name]["checksum"],
                                "clip": entry(chosen), "alignment": entry(matches[0])})
        if amendment:
            observed = [(row["speaker"], row["clip"]["member"], row["alignment"]["member"]) for row in choices]
            expected = [(row["logical_speaker"], row["unchanged_video_member"], row["raw_zenodo_alignment_member"])
                        for row in amendment["selected_sources"]]
            if observed != expected:
                raise ValueError("Amendment may not substitute any initially hash-selected clip")
        budget["candidate_universes_sha256"] = save_json(output / "candidate-universes.json", universes)
        freeze_selection(output, registration["protocol_sha256"], registration["official_metadata_sha256"],
                         choices, budget)
        print(f"all {len(choices)} selected source identities frozen sha256={budget['selection_sha256']}", flush=True)
        inventory, retained_alignments, attributions = [], {}, {}
        for choice in choices:
            sample = output / "originals" / f"s{choice['speaker']}"
            sample.mkdir(parents=True, exist_ok=False)
            align_path = sample / "original.align"
            retained_alignments[choice["speaker"]] = read_member(*open_archives["alignments.zip"], choice["alignment"], align_path)
            if amendment:
                attributions[choice["speaker"]] = verify_author_source(
                    choice, universes[str(choice["speaker"])], align_path, output, budget,
                    amendment["independent_author_source_gate"])
                print(f"author attribution {len(attributions)}/{len(choices)} {choice['source_id']}", flush=True)
        for choice in choices:
            sample = output / "originals" / f"s{choice['speaker']}"
            clip_path, align_path = sample / "original.mpg", sample / "original.align"
            clip = read_member(*open_archives[choice["archive"]], choice["clip"], clip_path)
            row = {**choice, "retained_video": clip, "retained_alignment": retained_alignments[choice["speaker"]],
                   "original_author_attribution": attributions.get(choice["speaker"]),
                   "word_alignment": alignment_rows(align_path), "format_inventory": inspect_original(clip_path, sample, tools)}
            if amendment:
                row["word_alignment"]["timebase_documented"] = False
                row["word_alignment"]["retained_clock_evidence"] = attributions[choice["speaker"]]
                row["word_alignment"]["candidate_seconds_not_independent_time_ground_truth"] = [
                    {"start": value["start_raw"] / amendment["independent_author_source_gate"]["zenodo_ticks_per_second"],
                     "end": value["end_raw"] / amendment["independent_author_source_gate"]["zenodo_ticks_per_second"],
                     "word": value["word"]} for value in row["word_alignment"]["raw_rows"]]
            save_json(sample / "source-inventory.json", row)
            inventory.append(row)
            print(f"retained {len(inventory)}/{len(choices)} {choice['source_id']} role={choice['role']}", flush=True)
        result = {"schema": "hepta.ndu-abc.grid-source-preparation-result.v1", "source_preparation_complete": True,
                  "source_selection_sha256": budget["selection_sha256"], "speaker_role_allocation": roles,
                  "sources_retained": len(inventory), "independent_evaluation_speaker_groups": len(roles["evaluation"]),
                  "actual_transferred_bytes": budget["transferred_bytes"], "http_request_count": budget["requests"],
                  "range_request_count": budget["requests"] - budget.get("full_tar_requests", 0),
                  "author_attribution_groups_passed": len(attributions),
                  "source_code_unchanged": registration["source_code_sha256"] == digest(Path(__file__).read_bytes()),
                  "scientific_experiment_C_passed": False, "task_outcomes_opened": False,
                  "natural_generator_joint_training_established": False, "cost": elapsed(before)}
        save_json(output / "summary.json", result)
        return result
    except BaseException as error:
        save_json(output / "failure.json", {"error": f"{type(error).__name__}: {error}",
                                           "traceback": traceback.format_exc(), "cost": elapsed(before),
                                           "download_budget": budget, "task_outcomes_opened": False})
        raise
    finally:
        for archive, reader in open_archives.values():
            archive.close()
            reader.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--protocol", required=True, type=Path)
    parser.add_argument("--official-metadata", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--source-amendment", type=Path)
    parser.add_argument("--mapping-evidence", type=Path)
    args = parser.parse_args()
    if bool(args.source_amendment) != bool(args.mapping_evidence):
        parser.error("--source-amendment and --mapping-evidence must be supplied together")
    print(json.dumps(prepare(args.protocol, args.official_metadata, args.output,
                             args.source_amendment, args.mapping_evidence), sort_keys=True), flush=True)


if __name__ == "__main__":
    main()
