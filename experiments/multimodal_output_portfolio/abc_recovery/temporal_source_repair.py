"""Verify a prospectively frozen GRID annotation directory repair against its author.

This is a source attribution check, without speech, lip-sync or controller scores.
Every selected recording stays fixed. Original and repackaged labels are retained.
"""

import ast
import io
from pathlib import Path, PurePosixPath
import tarfile
from urllib.request import Request, urlopen

from .temporal_sources import digest, elapsed, ledger, save, save_json, stamp, usage


def verified_mapping(amendment, evidence_path, protocol_sha):
    evidence = Path(evidence_path).read_bytes()
    if digest(evidence) != amendment["maintenance_evidence"]["source_sha256"]:
        raise ValueError("Pinned maintainer source differs from the registered repair evidence")
    if protocol_sha != amendment["superseded_protocol_sha256"]:
        raise ValueError("Repair amendment refers to a different original protocol")
    assignments = [node for node in ast.walk(ast.parse(evidence)) if isinstance(node, ast.Assign)
                   and any(isinstance(target, ast.Name) and target.id == "speaker_fix_map" for target in node.targets)]
    if len(assignments) != 1:
        raise ValueError("Expected one literal maintainer speaker correction mapping")
    fixed = ast.literal_eval(assignments[0].value)
    expected = amendment["video_logical_speaker_to_raw_zenodo_alignment_folder"]
    if any(fixed.get(f"s{speaker}") != f"s{raw}" for speaker, raw in expected.items()):
        raise ValueError("Proposed repair differs from the pinned maintainer mapping")
    return expected


def triples(raw):
    rows = []
    for line in raw.decode("utf-8").splitlines():
        fields = line.split()
        if len(fields) != 3:
            raise ValueError("Invalid original author annotation row")
        rows.append((int(fields[0]), int(fields[1]), fields[2]))
    return rows


def verify_original_tar(raw_tar, raw_zenodo_alignment, selected_stem, expected_stems, gate):
    """Require author attribution plus exact selected words and acoustic boundaries."""
    with tarfile.open(fileobj=io.BytesIO(raw_tar), mode="r:*") as archive:
        entries = [info for info in archive.getmembers() if info.isfile()
                   and PurePosixPath(info.name).suffix == ".align" and "__MACOSX" not in info.name]
        by_name = {PurePosixPath(info.name).stem: info for info in entries}
        if len(by_name) != len(entries) or set(by_name) != set(expected_stems):
            raise ValueError("Original author's own-speaker annotation universe differs from registered video universe")
        selected = by_name[selected_stem]
        if selected.size > 20000:
            raise ValueError("Unexpected original selected annotation size")
        original = archive.extractfile(selected).read(selected.size + 1)
    left, right = triples(original), triples(raw_zenodo_alignment)
    source_scale, target_scale = gate["source_original_ticks_per_second"], gate["zenodo_ticks_per_second"]
    original_scaled = [(begin * target_scale, end * target_scale, word) for begin, end, word in left]
    zenodo_scaled = [(begin * source_scale, end * source_scale, word) for begin, end, word in right]
    exact = original == raw_zenodo_alignment
    if (gate.get("require_exact_original_bytes") and not exact) or original_scaled != zenodo_scaled:
        raise ValueError("Selected original own-speaker annotation differs from proposed mapped Zenodo content or clock")
    return original, {"author_annotation_universe_count": len(by_name),
                      "author_annotation_universe_matches_video": True,
                      "original_tar_selected_member": selected.name,
                      "selected_words_and_boundaries_match_exactly": True,
                      "original_and_zenodo_bytes_identical": exact,
                      "selected_annotation_row_count": len(left),
                      "original_ticks_per_second": source_scale, "zenodo_ticks_per_second": target_scale,
                      "timebase_evidence": gate.get("word_timebase_status", "Predeclared tick conversion"),
                      "independent_lip_motion_ground_truth": False}


def verify_author_source(choice, expected_stems, alignment_path, output, budget, gate, transport=urlopen):
    """Retain the small original own-speaker tar and compare the frozen selection."""
    sample = Path(alignment_path).parent
    frozen = Path(output) / "selected-source-manifest.json"
    if digest(frozen.read_bytes()) != budget.get("selection_sha256"):
        raise ValueError("Selected source registration changed before author verification")
    limit = gate["maximum_tar_bytes"]
    if budget["transferred_bytes"] + limit > budget["limits"]["maximum_total_transferred_bytes"]:
        raise ValueError("Author provenance download would exceed registered total byte limit")
    url = gate["original_own_speaker_url"].format(speaker=choice["speaker"])
    if not url.startswith("https://spandh.dcs.shef.ac.uk/gridcorpus/"):
        raise ValueError("Original author URL is outside the approved domain")
    budget["requests"] += 1
    budget["full_tar_requests"] = budget.get("full_tar_requests", 0) + 1
    before = usage()
    row = {"request_id": budget["requests"], "phase": "original_author_annotation_attribution",
           "url": url, "at_utc": stamp(), "speaker": choice["speaker"], "http_range": False}
    try:
        request = Request(url, headers={"Accept-Encoding": "identity"})
        with transport(request, timeout=45) as response:
            raw = response.read(limit + 1)
            budget["transferred_bytes"] += len(raw)
            row.update(status=response.status, bytes=len(raw), etag=response.headers.get("ETag"),
                       last_modified=response.headers.get("Last-Modified"), final_url=response.geturl(),
                       sha256=save(sample / "official-own-speaker-align.tar", raw),
                       retained_response=str((sample / "official-own-speaker-align.tar").relative_to(output)))
            if response.status != 200 or len(raw) > limit:
                raise ValueError("Original author annotation response exceeds the registration or failed")
        selected_stem = PurePosixPath(choice["clip"]["member"]).stem
        original, comparison = verify_original_tar(raw, Path(alignment_path).read_bytes(), selected_stem,
                                                    expected_stems, gate)
        comparison.update(original_selected_sha256=save(sample / "official-original-selected.align", original),
                          original_tar_sha256=row["sha256"], original_author_url=url,
                          corrected_logical_speaker=choice["speaker"],
                          retained_raw_zenodo_alignment_speaker=choice["raw_alignment_speaker"],
                          original_author_attribution_gate_passed=True)
        save_json(sample / "annotation-attribution.json", comparison)
        return comparison
    except BaseException as error:
        row["error"] = f"{type(error).__name__}: {error}"
        raise
    finally:
        row["cost"] = elapsed(before)
        ledger(Path(output) / "range-requests.jsonl", row)
