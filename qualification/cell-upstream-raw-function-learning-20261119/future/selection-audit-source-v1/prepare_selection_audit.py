"""Retain the fixed ordered future-material decisions before any new generation."""

import hashlib
import json
from pathlib import Path
import time

ROOT = Path("/home/qian-qi/work/hepta-upstream-raw-function-learning-20261119-2e9b")
MATERIALS = ROOT / "future-materials-1"
OUT = ROOT / "future-panel-audit-1"
WEIGHTS = "237ae92fc94d6ae411671c671190314049ded5cdc0d5dae254d57c9d8bb67be6"
SELECTION = "540f2040ccb3cc0ded6d6c7205e3409fc557b60e421b6efdf0becbd6b050764b"
INVENTORY = "aa522307a3d06aba4ac355846cba05417c0a9dc06a88b834d618b414247c1d9a"
SELECTED = [
    (
        "lepture/mistune",
        "03-lepture--mistune/native-qualification-08-00-2",
        "37870292f6778129133f53f3f5f750956139a78a692d276446ecab183cf67d39",
        "2670acdf435b8b28bf92424cce2589d7a6796427ee91effcae9e8793c5e898e9",
        "0333de54ce946ea3d31641499a857fb5a018410830702b4b3023e428d42bbe2a",
        "future-license-review-1/LICENSE_REVIEW.json",
        "5fea20f520906bdc8340e32c71a77c7e95851edee3b15c571567dbc92ca366e0",
    ),
    (
        "python-babel/babel",
        "10-python-babel--babel/native-qualification-40-00-1",
        "d97ac97a481d41e239a5bca032a686f32f2fdd8ceab0d7b49d911fef74a767b9",
        "fefc362286d636c68ed226cba6c905e8637f89d065df8f38ca91fb913179d5e6",
        "f9587153ce127bdd9a4dd1bfd36a8389d6afd9e82065bae131ed51bfbf812869",
        "future-license-review-1/LICENSE_REVIEW.json",
        "5fea20f520906bdc8340e32c71a77c7e95851edee3b15c571567dbc92ca366e0",
    ),
    (
        "scrapy/w3lib",
        "13-scrapy--w3lib/native-qualification-21-00-v6-1",
        "782fe0a3e349a4f037708d47e2c4bebf024e68d315d222cbd69171af40b3637f",
        "dcd45cd883f3bad08163bc965da8c78c3f3bdbe016a038ac31ed89d8832945d1",
        "ee2ea3c2ef68c0a7244b649dedbba6ddca80c9b9c882f84a408457b95598bf8e",
        "future-license-review-w3lib-1/LICENSE_REVIEW.json",
        "825d29f895882b04cfaf7e1607473e851cd5f68616f5ca900e16265df5f44315",
    ),
    (
        "python-validators/validators",
        "14-python-validators--validators/native-qualification-00-00-v6-1",
        "fcae78431b8db95aa41295d845ec86506970026708c056668a56e90ae075b09a",
        "86e32ac46a81230a06b145544b3c60ce97ba367dafa54e7b866cee3a9afba762",
        "ecdc3e0fbbed7526c367c64ee8f0bc13b02486560fa1b24deaa27650c5287e7d",
        "future-license-review-validators-1/LICENSE_REVIEW.json",
        "5caac399d0bfa2763c74cd006e989ef75c27a14079805a58e3cd7c00e17d84cc",
    ),
]


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def ref(path):
    return {"path": str(path), "bytes": path.stat().st_size, "sha256": sha(path)}


def read(path, expected=None):
    raw = path.read_bytes()
    if expected is not None and hashlib.sha256(raw).hexdigest() != expected:
        raise ValueError("original input changed: " + str(path))
    return json.loads(raw)


def write(path, value):
    with path.open("x") as stream:
        stream.write(json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n")


def main():
    if (ROOT / "evaluation-A").exists() or (ROOT / "evaluation-future").exists():
        raise ValueError("new model generation domain already exists")
    weights = read(ROOT / "WEIGHTS_FROZEN.json", WEIGHTS)
    selection = read(MATERIALS / "FUTURE_PANEL_SELECTION_V2.json", SELECTION)
    inventory = read(
        ROOT / "future-preparation-old-inventory-1/DEDUP_INVENTORY.json", INVENTORY
    )
    old = {
        r.get("canonical_repository", r.get("repository"))
        for r in inventory["repositories"]
    }
    OUT.mkdir(exist_ok=False)
    selected, repos, inputs = [], [], []
    for (
        project,
        relative,
        pair_sha,
        context_sha,
        task_sha,
        license_rel,
        license_sha,
    ) in SELECTED:
        q = MATERIALS / relative
        prepared = q / "task-preparation-1"
        pair, context, task = (
            read(q / "RESULT.json", pair_sha),
            read(prepared / "RESULT.json", context_sha),
            read(prepared / "TASK.json", task_sha),
        )
        review = read(ROOT / license_rel, license_sha)
        if (
            pair["status"] != "ORIGINAL_NATIVE_PAIR_PASSED"
            or context["status"] != "CODEC_CONTEXT_DEDUP_PASSED_PENDING_LICENSE"
            or task["project_id"] != project
        ):
            raise ValueError("selected qualification differs")
        notices = [r for r in review["entries"] if r["canonical_repository"] == project]
        if (
            len(notices) != 1
            or not notices[0][
                "license_condition_for_current_material_retention_satisfied"
            ]
        ):
            raise ValueError("selected original license review missing")
        selected.append(
            {
                "preparation_root": str(prepared),
                "task_sha256": task_sha,
                "context_result_sha256": context_sha,
                "native_pair_sha256": pair_sha,
                "tokenizer_preflight_sha256": sha(
                    prepared / "TOKENIZER_PREFLIGHT.json"
                ),
                "license_review_path": str(ROOT / license_rel),
                "license_review_sha256": license_sha,
            }
        )
    order = selection["candidate_repositories_in_order"]
    last = order.index(SELECTED[-1][0])
    for index, requested in enumerate(order[: last + 1]):
        folder = MATERIALS / (f"{index:02d}-" + requested.replace("/", "--"))
        item = {"repository_index": index, "requested_repository": requested}
        if requested in old:
            item.update(
                status="EXCLUDED_OLD_PANEL_PROJECT_BEFORE_CONTENT",
                exclusion_inventory_sha256=INVENTORY,
                new_native_children=0,
            )
            repos.append(item)
            continue
        scan_path = folder / "RESULT.json"
        scan = read(scan_path)
        inputs.append(ref(scan_path))
        item.update(
            scan_result=ref(scan_path),
            canonical_repository=scan["canonical_repository"],
            frozen_HEAD=scan["HEAD"],
        )
        item["original_ordered_commits"] = [
            {
                "commit_index": n,
                "commit": c["commit"],
                "parent": c.get("parent"),
                "status": c["status"],
                "reason": c.get("reason"),
                "source_candidates": [
                    {
                        k: v
                        for k, v in s.items()
                        if k
                        in {
                            "status",
                            "reason",
                            "path",
                            "function",
                            "before_git_blob",
                            "after_git_blob",
                            "before_sha256",
                            "after_sha256",
                        }
                    }
                    for s in c.get("source_candidates", [])
                ],
            }
            for n, c in enumerate(scan["commits"])
        ]
        cap = folder / "CAPABILITY_QUALIFICATION.json"
        if cap.exists():
            value = read(cap)
            inputs.append(ref(cap))
            item["original_capability_gate"] = {
                "record": ref(cap),
                "status": value["status"],
                "decisions": [
                    {
                        k: v
                        for k, v in d.items()
                        if k
                        in {
                            "commit_index",
                            "source_index",
                            "commit",
                            "status",
                            "source_path",
                            "function",
                            "reason",
                            "error_type",
                        }
                    }
                    for d in value["decisions"]
                ],
            }
        attempts = []
        for q in sorted(folder.glob("native-qualification-*")):
            if not q.is_dir():
                continue
            entry = {"directory": str(q)}
            result_path = q / "RESULT.json"
            if result_path.exists():
                result = read(result_path)
                inputs.append(ref(result_path))
                entry.update(
                    record=ref(result_path),
                    status=result.get("status"),
                    commit_index=result.get("commit_index"),
                    source_index=result.get("source_index"),
                    actual_runtime_source_sha256=result.get("native_source_sha256"),
                    before={
                        k: result.get("before", {}).get(k)
                        for k in (
                            "actual_wait_returncode",
                            "tests",
                            "failures",
                            "errors",
                            "skipped",
                            "timed_out",
                        )
                    },
                    after={
                        k: result.get("after", {}).get(k)
                        for k in (
                            "actual_wait_returncode",
                            "tests",
                            "failures",
                            "errors",
                            "skipped",
                            "timed_out",
                        )
                    },
                    same_original_case_set=result.get("same_original_case_set"),
                )
            else:
                entry["status"] = (
                    "NO_TOP_LEVEL_RESULT_ORIGINAL_ATTEMPT_RETAINED_NO_SUCCESS_INFERRED"
                )
            context_path = q / "task-preparation-1/RESULT.json"
            if context_path.exists():
                c = read(context_path)
                inputs.append(ref(context_path))
                entry["complete_context"] = {
                    "record": ref(context_path),
                    "status": c.get("status"),
                    "first_tokens": c.get("first_tokens"),
                    "reference_tokens": c.get("reference_tokens"),
                    "planned_second_total": c.get("planned_second_total"),
                }
            attempts.append(entry)
        item["original_native_attempts_all_profiles"] = attempts
        item["selected"] = requested in {row[0] for row in SELECTED}
        if requested == "jquast/wcwidth":
            p = folder / "original-nonregular-qualification-1/RESULT.json"
            item["all_original_nonregular_rejections"] = ref(p)
            inputs.append(ref(p))
        repos.append(item)
    owner_records = []
    for folder in sorted(ROOT.glob("owned-future-*")):
        for path in sorted(folder.rglob("*.json")):
            if path.is_file():
                owner_records.append(ref(path))
    audit = {
        "schema": "hepta.ordered-future-material-selection-audit.v1",
        "created_at_ns": str(time.time_ns()),
        "weights_frozen_sha256": WEIGHTS,
        "weights_frozen_at_ns": weights["created_at_ns"],
        "selection_appendix_sha256": SELECTION,
        "selected_projects_in_declared_order": [row[0] for row in SELECTED],
        "stopped_after_repository_index": last,
        "unvisited_remaining_projects": order[last + 1 :],
        "repository_decisions": repos,
        "native_owner_raw_record_index": owner_records,
        "input_records": inputs,
        "new_model_calls": 0,
        "new_training_updates": 0,
        "new_evaluation_domains_absent": True,
        "student_outputs_used_for_selection": False,
        "original_case_errors_skips_timeouts_not_waived": True,
        "historical_profiles_retained_not_relabelled": True,
        "w3lib_v6_order_rule": "All original candidates before the first passing native/context candidate were replayed in original order with the unmodified declared pytest plugin. Older V5 failures remain unchanged; no later V6 candidate is needed after the first qualified task.",
        "known_dependency_metadata_exposure": [
            {
                "repository": "pallets/markupsafe",
                "scope": "Existing installed MarkupSafe metadata/files used only as original Jinja dependency before reaching repository index 20; no repair candidate was scanned or selected.",
            }
        ],
        "authenticated_users": 0,
        "authenticated_independent_controllers": 0,
        "pretraining_contamination_eliminated": False,
        "CPU_scopes": "Outer reaped launcher, inner isolated Python and whole-host windows are separate overlapping scopes; never summed as complete system compute.",
    }
    write(OUT / "SELECTION_AUDIT.json", audit)
    config = {
        "weights_frozen_sha256": WEIGHTS,
        "selection_path": str(MATERIALS / "FUTURE_PANEL_SELECTION_V2.json"),
        "selection_sha256": SELECTION,
        "selected": selected,
        "selection_audit_path": str(OUT / "SELECTION_AUDIT.json"),
        "selection_audit_sha256": sha(OUT / "SELECTION_AUDIT.json"),
    }
    write(OUT / "CONFIG.json", config)
    write(
        OUT / "RESULT.json",
        {
            "status": "ORDERED_AUDIT_AND_ASSEMBLY_CONFIG_READY",
            "source": ref(Path(__file__)),
            "files": [
                ref(OUT / name) for name in ("SELECTION_AUDIT.json", "CONFIG.json")
            ],
            "new_model_calls": 0,
            "new_native_children": 0,
            "new_training_updates": 0,
        },
    )
    print(json.dumps(read(OUT / "RESULT.json")), flush=True)


if __name__ == "__main__":
    main()
