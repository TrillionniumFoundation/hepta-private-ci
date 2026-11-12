"""Post-actor direct-ROI OCR upper bound; never a fair unknown-target control.

The complete frozen pilot must verify before any confirmation annotation opens.
Hidden category/word geometry selects the crop; annotation text never enters OCR
or the shared lexical decoder. Every selected task, including UNKNOWN, remains.
Local hashes establish byte custody, not independent or signed attestation.
"""

import argparse
import io
import math
import re
import shutil
import time
from pathlib import Path

from PIL import Image

from . import cord_task
from .entry import _json, _read_regular, read_pinned
from .owner import Owner
from .schema import canonical, digest, integer, real, require, sha
from .source_entry import backend_sha256
from .source_feature_profile import bind_head

CATEGORY = "total.total_price"
ARM = "direct_roi_ocr"
MAX_JSON = 4 * 1024 * 1024


def verified_pilot(args):
    """No annotation or image reads here; reject an incomplete actor panel first."""
    pilot = args.pilot.resolve()
    plan = _json(read_pinned(pilot / "PLAN.json", args.plan_sha256, MAX_JSON))
    done = _json(
        read_pinned(pilot / "ACTOR_DONE.json", args.actor_done_sha256, MAX_JSON)
    )
    require(plan["schema"] == "perc1.cord-pilot-plan.v1", "unknown pilot plan")
    integer(plan["seed"])
    require(
        done["all_results_retained"] is True and done["source_unchanged"] is True,
        "pilot actor completion is unverified",
    )
    index = _json(read_pinned(args.index, plan["input_index_sha256"], MAX_JSON))
    require(
        index["schema"] == "perc1.cord-index.v1" and index["success"] is True,
        "source acquisition incomplete",
    )
    head = _json(read_pinned(pilot / "HEAD.json", done["head_file_sha256"], MAX_JSON))
    profile = _json(
        read_pinned(pilot / "PROFILE.json", done["profile_file_sha256"], MAX_JSON)
    )
    require(
        sha(head) == done["head_sha256"] and sha(profile) == done["profile_sha256"],
        "frozen head/profile identity mismatch",
    )
    bind_head(profile, head)
    pins = plan["source_pins"]
    require(
        type(pins) is dict
        and {"cord_task.py", "cord_active.py", "owner.py", "source_capture.py"}
        <= set(pins)
        and len(pins) <= 128,
        "missing frozen pilot source pins",
    )
    for name, pin in pins.items():
        require(re.fullmatch(r"[A-Za-z0-9_]+\.py", name), "invalid source filename")
        read_pinned(Path(cord_task.__file__).with_name(name), pin, MAX_JSON)
    items = [item for item in index["sources"] if item["split"] == "confirmation"]
    arms = plan["arms"]
    require(
        len(items) == 12
        and type(arms) is list
        and 1 <= len(arms) <= 32
        and len(arms) == len(set(arms)),
        "oracle requires the fixed twelve-task pilot and unique arms",
    )
    identities = [item["id"] for item in items]
    require(len(set(identities)) == len(identities), "duplicate confirmation task")
    for name in identities + arms:
        require(re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}", name), "unsafe ID")
    expected = {(identity, arm) for identity in identities for arm in arms}
    roster = done["results"]
    require(
        type(roster) is list
        and len(roster) == len(expected)
        and {(r["task_id"], r["arm"]) for r in roster} == expected,
        "incomplete or duplicate actor roster",
    )
    for row in roster:
        path = pilot / "results" / (row["task_id"] + "-" + row["arm"] + ".json")
        record = _json(read_pinned(path, row["sha256"], MAX_JSON))
        require(
            record["schema"] == "perc1.cord-actor-result.v1"
            and (record["task_id"], record["arm"]) == (row["task_id"], row["arm"])
            and record["seed"] == plan["seed"]
            and record["status"] == row["status"]
            and record["status"] in ("COMPLETED", "UNKNOWN", "FAILED", "CANCELLED"),
            "actor identity/status mismatch",
        )
    return plan, index, profile


def roi_geometry(annotation, size):
    """Use category and quads only, including key words; never match target text."""
    width, height = size
    require(
        annotation["meta"]["image_size"] == {"width": width, "height": height},
        "annotation/image geometry mismatch",
    )
    points, selected = [], []
    lines = annotation["valid_line"]
    require(type(lines) is list and len(lines) <= 2048, "annotation line bound")
    for line_index, line in enumerate(lines):
        if line["category"] != CATEGORY:
            continue
        words = line["words"]
        require(type(words) is list and 0 < len(words) <= 128, "annotation word bound")
        quads = []
        for word in words:
            quad = word["quad"]
            coordinates = [
                [real(quad[f"x{i}"], 0, width), real(quad[f"y{i}"], 0, height)]
                for i in range(1, 5)
            ]
            points.extend(coordinates)
            quads.append(coordinates)
        selected.append(dict(line_index=line_index, word_quads=quads))
    require(points, "no annotated total-price ROI; task remains UNKNOWN")
    xs, ys = zip(*points)
    box = [
        max(0, math.floor(min(xs)) - 4),
        max(0, math.floor(min(ys)) - 4),
        min(width, math.ceil(max(xs)) + 4),
        min(height, math.ceil(max(ys)) + 4),
    ]
    require(box[0] < box[2] and box[1] < box[3], "empty oracle ROI")
    return dict(category=CATEGORY, selected_lines=selected, box=box, padding_pixels=4)


def execute(item, profile, plan, revision, root, ocr):
    """One actual ordinary-owner OCR attempt; failures retain elapsed costs."""
    started, cpu = time.perf_counter_ns(), time.process_time_ns()
    directory = root / item["id"]
    directory.mkdir(mode=0o700)
    record = dict(
        schema="perc1.cord-oracle-result.v1",
        task_id=item["id"],
        source_group=item["id"],
        arm=ARM,
        seed=plan["seed"],
        classification="oracle_upper_bound",
        information="hidden_roi",
        status="UNKNOWN",
        answer=None,
        quality=None,
        receipt_sha256=None,
        image_sha256=item["image_sha256"],
        annotation_sha256=item["annotation_sha256"],
        encoder_calls=0,
        ocr_calls=None,
        owner_status=None,
        scientific_status="HOLD",
        adoption="NoUpdate",
        fair_comparator=False,
    )
    dispatch_ns, recovery_ns = None, None
    try:
        annotation_raw = read_pinned(
            item["annotation_path"], item["annotation_sha256"], MAX_JSON
        )
        annotation = _json(annotation_raw)
        with (directory / "annotation.json").open("xb") as stream:
            stream.write(annotation_raw)
        image_raw = read_pinned(item["image_path"], item["image_sha256"], 4 * MAX_JSON)
        with (directory / "original.image").open("xb") as stream:
            stream.write(image_raw)
        with Image.open(io.BytesIO(image_raw)) as image:
            require(image.getexif().get(274, 1) == 1, "explicit orientation required")
            require(image.width * image.height <= 16_000_000, "image pixel bound")
            geometry = roi_geometry(annotation, image.size)
            view = image.convert("RGB").crop(geometry["box"])
        view.save(directory / "roi.png")
        roi_raw = _read_regular(directory / "roi.png", MAX_JSON)
        transform = dict(
            schema="perc1.cord-oracle-transform.v1",
            **geometry,
            original_sha256=item["image_sha256"],
            annotation_sha256=item["annotation_sha256"],
            roi_sha256=sha(roi_raw),
            output_size=list(view.size),
            resize=None,
            annotation_path=item["annotation_path"],
            original_path=item["image_path"],
            decoder="unchanged cord_task.decode; no annotation text supplied",
        )
        cord_task.write(directory / "TRANSFORM.json", transform)
        record["transform_sha256"] = sha((directory / "TRANSFORM.json").read_bytes())
        source = dict(
            schema="perc1.source-capture.v1",
            kind="document_page",
            image=dict(path=str(directory / "roi.png"), sha256=sha(roi_raw)),
            source_uri=f"https://huggingface.co/datasets/naver-clova-ix/cord-v2/tree/{revision}#{item['id']}/oracle",
            source_group=item["id"],
            text=None,
            ocr=ocr,
            document=dict(
                path=str(directory / "original.image"),
                sha256=item["image_sha256"],
                page_index=0,
            ),
        )
        source_id = "oracle_roi"
        sources = {source_id: source}
        grant = dict(
            schema="perc1.capture-grant.v1",
            owner_id="oracle:" + item["id"],
            generation=1,
            source_ids=[source_id],
            scope_digest=sha(transform),
            source_frontier=sha(
                dict(sources=sources, capture_backend_sha256=backend_sha256())
            ),
        )
        binding = {
            **{k: grant[k] for k in ("owner_id", "generation", "source_frontier")},
            "grant_sha256": sha(grant),
            "encoder_sha256": profile["latent_model_digest"],
        }
        cord_task.write(
            directory / "BINDING.json",
            dict(binding=binding, grant=grant, source=source),
        )
        task = dict(sources=sources, requests={source_id: dict(source_id=source_id)})
        with Owner(directory / "owner", binding, 1) as owner:
            receipt = cord_task.acquire(owner, None, task, source_id, neural=False)
            record.update(
                receipt_sha256=receipt["receipt_sha256"],
                owner_status=owner.status(),
                owner_receipt_status=receipt["status"],
                owner_error=receipt["error"],
            )
            dispatch_ns = receipt["measurements"]["wall_ns"]
            answer = cord_task.decode(cord_task.text(owner, receipt))
            record["ocr_calls"] = 1
        begin = time.perf_counter_ns()
        with Owner(directory / "owner", binding, 1) as cold:
            restored = cold.receipt(source_id)
            require(restored == receipt, "cold oracle receipt changed")
            require(
                cord_task.decode(cord_task.text(cold, restored)) == answer,
                "cold OCR answer changed",
            )
        recovery_ns = time.perf_counter_ns() - begin
        target = annotation.get("gt_parse", {}).get("total", {}).get("total_price")
        known = type(target) is str and any(c.isdigit() for c in target)
        record.update(
            status="COMPLETED",
            answer=answer,
            quality=float(answer == cord_task.normalize_amount(target))
            if known
            else None,
        )
    except Exception as error:
        record["error"] = dict(type=type(error).__name__, message=str(error)[:1000])
    record["cost"] = dict(
        inclusive_wall_ns=time.perf_counter_ns() - started,
        process_cpu_ns=time.process_time_ns() - cpu,
        dispatch_nested_wall_ns=dispatch_ns,
        recovery_nested_wall_ns=recovery_ns,
        energy_joules=None,
        provider_billing=None,
        historical_capture_cost=None,
        ocr_subprocess_cpu_ns=None,
        scope="oracle invocation including label/ROI preparation, dispatch, decode and cold read; nested times never additive; no fair-panel allocation",
    )
    path = directory / "RESULT.json"
    cord_task.write(path, record)
    return record, sha(path.read_bytes())


def run(args):
    started = time.perf_counter_ns()
    plan, index, profile = verified_pilot(args)
    executable = shutil.which("tesseract")
    require(executable is not None, "Tesseract required")
    executable = Path(executable).resolve()
    ocr = dict(
        executable=str(executable),
        sha256=sha(_read_regular(executable, 16 * MAX_JSON)),
        language="eng",
        psm=6,
    )
    root = args.output.resolve()
    require(
        not root.is_relative_to(args.pilot.resolve()),
        "oracle output must be separate from frozen pilot",
    )
    root.mkdir(mode=0o700, parents=True, exist_ok=False)
    code_pin = sha(Path(__file__).read_bytes())
    items = [item for item in index["sources"] if item["split"] == "confirmation"]
    frozen = dict(
        schema="perc1.cord-oracle-plan.v1",
        pilot=str(args.pilot.resolve()),
        plan_sha256=digest(args.plan_sha256),
        actor_done_sha256=digest(args.actor_done_sha256),
        input_index_sha256=plan["input_index_sha256"],
        oracle_code_sha256=code_pin,
        confirmation_ids=[item["id"] for item in items],
        original_arms=plan["arms"],
        ocr=ocr,
        geometry="union of all total.total_price word quads; 4-pixel padding; no resize",
        decoder="unchanged cord_task.decode",
        quality="digit-string equality after punctuation/leading-zero removal",
        classification="oracle_upper_bound",
        fair_comparator=False,
        scientific_status="HOLD",
        adoption="NoUpdate",
        preflight_wall_ns=time.perf_counter_ns() - started,
    )
    cord_task.write(root / "PLAN.json", frozen)
    rows, originals = [], []
    for item in items:
        row, pin = execute(item, profile, plan, index["revision"], root, ocr)
        rows.append(row)
        originals.append(
            dict(
                task_id=item["id"],
                status=row["status"],
                sha256=pin,
                relative_path=item["id"] + "/RESULT.json",
            )
        )
        print(canonical(originals[-1]).decode(), flush=True)
    unchanged, error = True, None
    try:
        require(sha(Path(__file__).read_bytes()) == code_pin, "oracle source changed")
        require(
            verified_pilot(args) == (plan, index, profile),
            "pilot changed during oracle",
        )
    except Exception as failure:
        unchanged, error = False, str(failure)[:1000]
    report = dict(
        schema="perc1.cord-oracle-report.v1",
        scientific_status="HOLD",
        adoption="NoUpdate",
        classification="oracle_upper_bound",
        fair_comparator=False,
        measured_net_benefit=None,
        plan_file_sha256=sha((root / "PLAN.json").read_bytes()),
        results=originals,
        all_results_retained=len(rows) == len(items),
        frozen_inputs_unchanged=unchanged,
        verification_error=error,
        tasks=len(rows),
        completed=sum(r["status"] == "COMPLETED" for r in rows),
        correct=sum(r["quality"] == 1 for r in rows),
        unknown_quality=sum(r["quality"] is None for r in rows),
        total_inclusive_wall_ns=sum(r["cost"]["inclusive_wall_ns"] for r in rows),
        cost_scope="independent oracle ledger; excludes initial preflight and final reporting; energy/billing/history/child CPU unknown",
        original_capture_authenticated=False,
        source_independence_verified=False,
    )
    cord_task.write(root / "REPORT.json", report)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("pilot", "index", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    for name in ("plan-sha256", "actor-done-sha256"):
        parser.add_argument("--" + name, required=True)
    args = parser.parse_args()
    return 0 if run(args)["frozen_inputs_unchanged"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
