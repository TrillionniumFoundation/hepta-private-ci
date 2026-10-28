"""Independent source audit and batched scoring of archived actual media.

No generator is imported, loaded or called. Targets are rebuilt from pinned
original pixels plus the recorded public swap, checked against the input RNG.
The original reward observer is the primary check. A separate audit observer
is reported only as sensitivity under its own observer/profile identity.
"""

import argparse
from dataclasses import replace
import gzip
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import time
import zipfile

import numpy as np
from PIL import Image
import torch

from ..closure_v2_20261027.allocate_admission_sources import source_ids
from ..continuation_20261027.joint.data import historical_corpus, fresh_corpus
from ..v6.data import SourceCorpus, SourceSplit, _parse_images, _parse_labels
from ..v6.observer import METRIC, Recognizer, observe_tensors
from .profile import CostEvent, NduProfile, aggregate, digest, total_cost


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def source_audit(assets, development):
    assets, development = Path(assets), Path(development)
    allocation_path = development / "SOURCE_ALLOCATION.json"
    allocation = json.loads(allocation_path.read_text())
    protocol = json.loads((development / "PROTOCOL.json").read_text())
    seal = json.loads((development / "DEVELOPMENT_SEAL.json").read_text())
    for key, name in (("source_allocation_sha256", "SOURCE_ALLOCATION.json"),
                      ("protocol_sha256", "PROTOCOL.json"), ("selection_sha256", "SELECTIONS.json")):
        if seal[key] != sha(development / name):
            raise ValueError("Qualification source/protocol/selection changed after development")
    if seal["smoke_only"] or seal["qualification_predictions"] != 0:
        raise ValueError("Independent qualification requires sealed non-smoke development")
    historical = historical_corpus(assets)
    previous = fresh_corpus(assets, historical)
    old_fresh_sha = hashlib.sha256((json.dumps(previous.manifest, indent=2, sort_keys=True) + "\n").encode()).hexdigest()
    prior = Path(__file__).resolve().parent.parent / "closure_v2_20261027"
    historical_hashes = {h for split in historical.splits.values() for h in split.pixel_hashes}
    exclusions = {"historical": historical_hashes,
                  "prior_fresh": {h for split in previous.splits.values() for h in split.pixel_hashes}}
    original = json.loads((assets / "ndu-runs/full-002/protocol.json").read_text())
    exclusions["prior_heldout"] = set(original.get("prior_heldout_exclusion", {}).get("source_pixel_sha256", []))
    for name in ("SOURCE_ALLOCATION.json", "CONTROL_ADMISSION_SOURCE_ALLOCATION.json"):
        path = prior / name
        if sha(path) != allocation["prior_allocation_pins"][name]:
            raise ValueError("Prior allocation exclusion pin changed")
        document = json.loads(path.read_text())
        exclusions[name] = {i.rsplit(":", 1)[1] for i in source_ids(document)}
        if name == "SOURCE_ALLOCATION.json" and old_fresh_sha != document["prior_manifest_sha256"]:
            raise ValueError("Recreated previous-fresh sources differ from the historical manifest")
    images_path = assets / "ndu-data/t10k-images-idx3-ubyte.gz"
    labels_path = assets / "ndu-data/t10k-labels-idx1-ubyte.gz"
    if sha(images_path) != allocation["official_image_sha256"] or sha(labels_path) != allocation["official_label_sha256"]:
        raise ValueError("Official image or label bytes changed")
    images, hashes = _parse_images(gzip.decompress(images_path.read_bytes()))
    labels = _parse_labels(gzip.decompress(labels_path.read_bytes()))
    labels_by_hash = {}
    for pixel_hash, label in zip(hashes, labels.tolist()):
        labels_by_hash.setdefault(pixel_hash, set()).add(label)
    expected_counts = {"test": 2 * protocol["qualification_pairs"], "retention": 2 * protocol["retention_pairs"]}
    if set(allocation["splits"]) != set(expected_counts):
        raise ValueError("Unexpected held-out source partitions")
    splits, used, overlap = {}, set(), {}
    for name, group in allocation["splits"].items():
        identities = tuple(group["source_ids"])
        if len(identities) != expected_counts[name]:
            raise ValueError("Source population size differs from the frozen protocol")
        indices = [int(identity.split(":")[2]) for identity in identities]
        selected = tuple(hashes[index] for index in indices)
        if (len(set(selected)) != len(selected) or used.intersection(selected)
                or any(len(labels_by_hash[h]) != 1 for h in selected)):
            raise ValueError("Duplicate, cross-split or ambiguous-label original pixels")
        if any(identity != f"mnist:test:{index}:{h}" for identity, index, h in zip(identities, indices, selected)):
            raise ValueError("Declared original pixel identity differs from actual source bytes")
        overlap[name] = {key: len(set(selected) & reserved) for key, reserved in exclusions.items()}
        if any(overlap[name].values()):
            raise ValueError("New qualification reuses a known reserved original pixel")
        used.update(selected)
        splits[name] = SourceSplit(images[indices].clone(), labels[indices].clone(), identities, selected)
    report = {"allocation_sha256": sha(allocation_path), "recreated_prior_fresh_manifest_sha256": old_fresh_sha,
              "source_counts": expected_counts, "known_excluded_pool_sizes": {k: len(v) for k, v in exclusions.items()},
              "overlap_counts": overlap, "mutually_disjoint": True, "writer_independence_established": False,
              "all_historical_global_usage_known": False, "model_predictions_performed": 0}
    return SourceCorpus(splits, allocation), report


@torch.inference_mode()
def audit_evaluation(directory, corpus, protocol, profile, semantics, reward, audit_observer, audit_profile,
                     *, batch_size=128, tolerance=1e-6):
    directory = Path(directory)
    record = json.loads((directory / "EVALUATION.json").read_text())
    if record["profile_sha256"] != profile.digest or set(record["groups"]) != {"quality", "retention"}:
        raise ValueError("Evaluation profile or task scopes differ from the study")
    binding = record["policy_binding"]
    mode = "prior_deterministic" if record["deterministic"] else "fullpath_stochastic"
    if (digest(binding) != record["policy_sha256"] or binding["profile_sha256"] != profile.digest
            or binding["emission_mode"] != mode or mode not in semantics["continuation"]["emission_modes"]):
        raise ValueError("Evaluation policy mode or its binding changed")
    k = protocol["qualification_emissions"]
    tariffs = semantics["continuation"]["tariffs"]
    counts = {"encoder": 2, "gate": 1, "transition": semantics["continuation"]["horizon"],
              "pixel_emission": 1, "token_emission": protocol["emission"]["latent_token_steps"],
              "write": 2, "read": 2, "observer": 1}
    archive_hashes, seen_draws, seen_costs = {}, set(), set()
    checked, queued, errors = 0, [], []
    values = {scope: {"reward": {}, "audit": {}} for scope in record["groups"]}
    strict = {scope: {"reward": 0, "audit": 0, "draws": 0} for scope in record["groups"]}

    def score_batch():
        nonlocal checked
        if not queued:
            return
        pixels = torch.cat([item[1] for item in queued])
        captions = [item[2] for item in queued]
        targets = torch.cat([item[3] for item in queued])
        labels = torch.cat([item[4] for item in queued])
        primary_scores = observe_tensors(reward, pixels, captions, targets, labels)
        sensitivity_scores = observe_tensors(audit_observer, pixels, captions, targets, labels)
        for (row, _, _, _, _, charge), primary_score, other_score in zip(queued, primary_scores, sensitivity_scores):
            difference = abs(primary_score["utility"] - charge - row["net_return"])
            errors.append(difference)
            if difference > tolerance or abs(primary_score["utility"] - row["gross_utility"]) > tolerance:
                raise ValueError("Reopened media do not reproduce the primary observed return")
            for field, value in primary_score.items():
                recorded = row["score"][field]
                if isinstance(value, float):
                    if abs(value - recorded) > tolerance:
                        raise ValueError("Reopened media differ in a primary score component")
                elif value != recorded:
                    raise ValueError("Reopened media differ in primary decoded semantics")
            scope, context = row["scope"], row["context_id"]
            for label, score in (("reward", primary_score), ("audit", other_score)):
                values[scope][label].setdefault(context, []).append(score["utility"] - charge)
                strict[scope][label] += int(score["text_fact"] == 0 and score["relation"] == 0 and score["image_fact"] == 0)
            strict[scope]["draws"] += 1
            checked += 1
        queued.clear()

    for scope, group in record["groups"].items():
        archives = {}
        conditions = protocol["conditions"] if scope == "quality" else ["clean"]
        pair_count = protocol["qualification_pairs"] if scope == "quality" else protocol["retention_pairs"]
        if len(group["rows"]) != pair_count * len(conditions) * k:
            raise ValueError("Observed cohort dropped an output or condition")
        for row in group["rows"]:
            if row["scope"] != scope or row["condition"] not in conditions:
                raise ValueError("Row scope or condition does not match its cohort")
            archives.setdefault(row["archive"], []).append(row)
        for archive_name, rows in archives.items():
            if PurePosixPath(archive_name).name != archive_name:
                raise ValueError("Archive reference must be local to its evaluation")
            archive_path = directory / archive_name
            archive_hashes[archive_name] = sha(archive_path)
            n = len(rows) // k
            if len(rows) != n * k or n < 1 or n > protocol["batch_size"]:
                raise ValueError("Unexpected batched emission multiplicity")
            offsets = sorted({row["source_offset"] for row in rows})
            start = offsets[0]
            if offsets != list(range(start, start + n)) or start < 0 or start + n > pair_count:
                raise ValueError("Missing or noncontiguous original source pairs in a batch")
            condition = rows[0]["condition"]
            if archive_name != f"{scope}-{condition}-{start:04d}.zip":
                raise ValueError("Archive batch identity differs from its source range")
            expected_seed = 28199131 + start + conditions.index(condition) * 10007
            swaps = torch.randint(2, (n,), generator=torch.Generator().manual_seed(expected_seed)).bool()
            with zipfile.ZipFile(archive_path) as archive:
                members = archive.namelist()
                required = [name for row in rows for name in row["artifacts"].values()]
                if (len(set(members)) != len(members) or len(set(required)) != len(required)
                        or set(members) != set(required) or len(required) != 2 * len(rows)):
                    raise ValueError("Archived media inventory differs from actual output receipts")
                for row in rows:
                    index = row["source_offset"] - start
                    if (row["condition"] != condition or row["batch_seed"] != expected_seed
                            or row["target_swap"] != bool(swaps[index])):
                        raise ValueError("Recorded public command differs from the frozen input construction")
                    source_name = "test" if scope == "quality" else "retention"
                    if (row["source_split"] != source_name or row["profile_sha256"] != profile.digest
                            or row["policy_sha256"] != record["policy_sha256"]):
                        raise ValueError("Output row has a changed source/profile binding")
                    source = corpus.splits[source_name]
                    offset = 2 * row["source_offset"]
                    pair = tuple(source.ids[offset:offset + 2])
                    pair_id = digest({"original_pixel_sources": sorted(pair)})
                    if (tuple(row["source_ids"]) != pair or row["source_cluster_id"] != pair_id
                            or row["context_id"] != f"{condition}:{pair_id}"):
                        raise ValueError("Sample is not bound to its original source pair")
                    draw = int(row["sample_id"].rsplit(":draw-", 1)[-1])
                    if (row["seed"] != record["seed"] or row["sample_id"] != f"seed-{record['seed']}:draw-{draw}"
                            or not 0 <= draw < k):
                        raise ValueError("Unknown or out-of-range sample draw identity")
                    emitted_index = draw * n + index
                    if row["artifacts"] != {"image": f"out-{emitted_index:04d}/image.png",
                                            "text": f"out-{emitted_index:04d}/caption.txt"}:
                        raise ValueError("Sample draw identity differs from its actual emitted artifact")
                    identity = (row["context_id"], row["sample_id"])
                    if identity in seen_draws or row["terminal_kind"] != "delivered":
                        raise ValueError("Duplicate sample or unaccounted failure/refusal")
                    seen_draws.add(identity)
                    costs = tuple(CostEvent(**entry) for entry in row["costs"])
                    expected = {kind: units * tariffs[kind] for kind, units in counts.items()}
                    if len(costs) != len(expected) or {c.kind: c.amount for c in costs} != expected:
                        raise ValueError("Actual trajectory ledger differs from the frozen tariff contract")
                    if seen_costs.intersection(c.event_id for c in costs):
                        raise ValueError("Distinct executed outputs reused a cost event identity")
                    seen_costs.update(c.event_id for c in costs)
                    charge = total_cost(profile, costs)
                    raw_image, raw_text = (archive.read(row["artifacts"][kind]) for kind in ("image", "text"))
                    if any(hashlib.sha256(raw).hexdigest() != row["artifact_sha256"][kind]
                           for kind, raw in (("image", raw_image), ("text", raw_text))):
                        raise ValueError("Archived delivered bytes changed")
                    with Image.open(io.BytesIO(raw_image)) as image:
                        if image.format != "PNG" or image.mode != "L" or image.size != (56, 28):
                            raise ValueError("Delivered PNG differs from the registered media format")
                        pixels = torch.from_numpy(np.array(image, copy=True)).float()[None, None] / 255
                    caption = raw_text.decode("utf-8")
                    if caption != row["caption"] or len(caption) > 4096:
                        raise ValueError("Actual UTF-8 differs from its delivery receipt")
                    target = torch.cat((source.images[offset], source.images[offset + 1]), dim=2).float()[None] / 255
                    labels = source.labels[offset:offset + 2]
                    if row["target_swap"]:
                        target = torch.cat((target[:, :, :, 28:], target[:, :, :, :28]), dim=3)
                        labels = labels.flip(0)
                    if labels.tolist() != row["target_labels"]:
                        raise ValueError("Recorded labels differ from the independently rebuilt target")
                    queued.append((row, pixels, caption, target, labels[None], charge))
                    if len(queued) >= batch_size:
                        score_batch()
    score_batch()
    summaries = {}
    for scope in values:
        primary = aggregate(profile, values[scope]["reward"])
        primary.pop("contexts")
        if abs(primary["value"] - record["groups"][scope]["summary"]["value"]) > tolerance:
            raise ValueError("Archived primary return aggregation differs from published results")
        secondary = aggregate(audit_profile, values[scope]["audit"])
        secondary.pop("contexts")
        summaries[scope] = {"primary_reward": primary, "independent_observer_sensitivity": secondary,
                            "strict_counts": strict[scope]}
    return {"evaluation_sha256": sha(directory / "EVALUATION.json"), "seed": record["seed"],
            "policy_sha256": record["policy_sha256"], "emission_mode": mode,
            "bundles_reopened": checked, "archive_sha256": archive_hashes,
            "maximum_primary_return_discrepancy": max(errors, default=0.), "groups": summaries,
            "cost_units": "frozen per-deployment logical work tariff; physical training batching measured separately"}


def run(*, assets, development, qualification, output, batch_size=128):
    wall, cpu = time.perf_counter(), time.process_time()
    assets, development, qualification, output = map(Path, (assets, development, qualification, output))
    if output.exists():
        raise FileExistsError("Preserve previous independent audit evidence")
    if isinstance(batch_size, bool) or not isinstance(batch_size, int) or batch_size < 1:
        raise ValueError("Positive batch size required")
    protocol = json.loads((development / "PROTOCOL.json").read_text())
    profile = NduProfile.from_dict(json.loads((development / "PROFILE.json").read_text()))
    semantics = json.loads((development / "SEMANTICS.json").read_text())
    result = json.loads((qualification / "RESULT.json").read_text())
    development_seal = json.loads((development / "DEVELOPMENT_SEAL.json").read_text())
    qualification_seal = json.loads((qualification / "QUALIFICATION_SEAL.json").read_text())
    if (development_seal["profile_sha256"] != profile.digest or result["profile_sha256"] != profile.digest
            or qualification_seal["profile_sha256"] != profile.digest
            or qualification_seal["development_seal_sha256"] != sha(development / "DEVELOPMENT_SEAL.json")
            or qualification_seal["allocation_sha256"] != sha(development / "SOURCE_ALLOCATION.json")
            or qualification_seal["selected"] != json.loads((development / "SELECTIONS.json").read_text())):
        raise ValueError("Qualification profile/selection/frozen-development chain changed")
    reward_path, audit_path = (assets / f"ndu-runs/full-002/{name}-observer.pt" for name in ("reward", "audit"))
    restored = json.loads((assets / "RESTORATION.json").read_text())
    restored_hashes = {entry["path"]: entry["sha256"] for entry in restored["selected_files"]}
    if any(sha(path) != restored_hashes[str(path.relative_to(assets))] for path in (reward_path, audit_path)):
        raise ValueError("Frozen reward or sensitivity observer differs from restored original bytes")
    observer_spec = {"weights_file_sha256": sha(reward_path), "metric": METRIC,
                     "observer_code_sha256": sha(Path(__file__).resolve().parent.parent / "v6/observer.py")}
    if observer_spec != semantics["observer"] or digest(observer_spec) != profile.observer_sha256:
        raise ValueError("Actual primary observer differs from the frozen objective")
    if digest(semantics["objective"]) != profile.objective_sha256 or digest(semantics["continuation"]) != profile.continuation_sha256:
        raise ValueError("Objective/continuation semantics changed")
    audit_spec = {**observer_spec, "weights_file_sha256": sha(audit_path)}
    audit_profile = replace(profile, observer_sha256=digest(audit_spec))
    torch.set_num_threads(protocol["threads"])
    torch.use_deterministic_algorithms(True)
    reward, audit_observer = Recognizer().eval().requires_grad_(False), Recognizer().eval().requires_grad_(False)
    reward.load_state_dict(torch.load(reward_path, weights_only=True, map_location="cpu"))
    audit_observer.load_state_dict(torch.load(audit_path, weights_only=True, map_location="cpu"))
    corpus, sources = source_audit(assets, development)
    audits = []
    for entry in result["per_seed_arm"]:
        directory = qualification / f"seed-{entry['seed']}-{entry['arm']}"
        if sha(directory / "EVALUATION.json") != entry["evaluation_sha256"]:
            raise ValueError("Published qualification changed before independent readback")
        checked = audit_evaluation(directory, corpus, protocol, profile, semantics, reward, audit_observer,
                                   audit_profile, batch_size=batch_size)
        audits.append({"arm": entry["arm"], **checked})
        print(f"audited seed={entry['seed']} arm={entry['arm']} bundles={checked['bundles_reopened']}", flush=True)
    total_bundles = sum(r["bundles_reopened"] for r in audits)
    if (total_bundles != result["counts_and_timing"]["actual_bundles"]
            or 2 * total_bundles != result["counts_and_timing"]["files_written_and_reopened"]):
        raise ValueError("Physical output counts differ from the complete qualification receipt")
    report = {"schema": "hepta.ndu.independent-fullpath-media-audit.v1", "passed": True,
              "profile_sha256": profile.digest, "primary_reward_observer": observer_spec,
              "sensitivity_observer": audit_spec, "sensitivity_profile_sha256": audit_profile.digest,
              "qualification_result_sha256": sha(qualification / "RESULT.json"),
              "audit_source_sha256": sha(__file__), "source_exclusion_audit": sources,
              "per_seed_arm": audits, "total_bundles_reopened": total_bundles,
              "maximum_primary_return_discrepancy": max(r["maximum_primary_return_discrepancy"] for r in audits),
              "generator_calls": 0, "checkpoint_or_selection_mutations": 0,
              "separate_observer_used_for_promotion": False, "batch_size": batch_size,
              "wall_seconds": time.perf_counter() - wall, "cpu_seconds": time.process_time() - cpu}
    output.write_text(json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + "\n")
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("assets", "development", "qualification", "output"):
        parser.add_argument("--" + name, required=True, type=Path)
    parser.add_argument("--batch-size", type=int, default=128)
    args = parser.parse_args()
    report = run(**vars(args))
    print(json.dumps({key: report[key] for key in ("passed", "total_bundles_reopened",
          "maximum_primary_return_discrepancy", "generator_calls", "wall_seconds")}))
