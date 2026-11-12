"""Freeze and retain fixed CORD-v2 rows from official revision-pinned Parquet.

Original dataset-embedded bytes are preserved. This does not authenticate a
scanner original or establish globally unseen sources. Labels stay separate.
"""

import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
import time
import urllib.request

DATASET = "naver-clova-ix/cord-v2"
REVISION = "7f0115a4b758a71d6473b8d085751692da2fef98"
COUNTS = {"train": 24, "validation": 8, "test": 12}


def require(ok, message):
    if not ok:
        raise ValueError(message)


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def file_sha(path):
    value = hashlib.sha256()
    with Path(path).open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            value.update(chunk)
    return value.hexdigest()


def write(path, value):
    raw = (
        value
        if type(value) is bytes
        else (json.dumps(value, sort_keys=True, indent=2) + "\n").encode()
    )
    with Path(path).open("xb") as stream:
        stream.write(raw)
    return sha(raw)


class Redirects(urllib.request.HTTPRedirectHandler):
    def __init__(self):
        self.records = []

    def redirect_request(self, request, fp, code, msg, headers, newurl):
        self.records.append(
            {
                "request_url": request.full_url,
                "status": code,
                "response_headers": dict(headers),
                "redirect_url": newurl,
            }
        )
        return super().redirect_request(request, fp, code, msg, headers, newurl)


def request(url):
    redirects = Redirects()
    response = urllib.request.build_opener(redirects).open(url, timeout=90)
    provenance = dict(
        request_url=url,
        request_headers={},
        redirects=redirects.records,
        final_url=response.url,
        status=response.status,
        response_headers=dict(response.headers),
    )
    return response, provenance


def plan(root):
    root = Path(root)
    root.mkdir(mode=0o700)
    metadata = {}
    for name, url in {
        "dataset": f"https://huggingface.co/api/datasets/{DATASET}",
        "tree": f"https://huggingface.co/api/datasets/{DATASET}/tree/{REVISION}/data?recursive=false&expand=false",
    }.items():
        with_response, headers = request(url)
        with with_response as response:
            raw = response.read(4 * 1024 * 1024 + 1)
        require(len(raw) <= 4 * 1024 * 1024, "metadata response bound")
        write(root / (name + "-response.json"), raw)
        write(root / (name + "-headers.json"), headers)
        metadata[name] = json.loads(raw)
    require(
        metadata["dataset"]["sha"] == REVISION, "dataset revision changed before plan"
    )
    files = {}
    for split in COUNTS:
        matches = [
            v
            for v in metadata["tree"]
            if v["path"].startswith("data/" + split + "-00000-of-")
        ]
        require(len(matches) == 1, "ambiguous first shard")
        item = matches[0]
        files[split] = dict(
            path=item["path"],
            bytes=item["size"],
            sha256=item["lfs"]["oid"],
            git_blob=item["oid"],
        )
    value = dict(
        schema="perc1.cord-source-plan.v1",
        dataset=DATASET,
        revision=REVISION,
        counts=COUNTS,
        selection="first rows of first original shard, without replacement or skipping",
        indices={s: list(range(n)) for s, n in COUNTS.items()},
        shards=files,
        exposed_before_plan={"train": [0, 1, 2, 3, 4], "validation": [], "test": []},
        prior_exposure_scope="root saw HF train viewer rows 0-4 before this plan; absence of other global exposure is unverified",
        image_source="exact bytes embedded in original revision-pinned dataset Parquet; scanner-original authenticity unverified",
        labels="separate evaluator directory; never emit annotation values",
        failure_policy="retain failed attempt and fail whole fixed cohort; never substitute rows",
        scientific_qualified=False,
        source_independence_verified=False,
        original_capture_authenticated=False,
        adoption="NoUpdate",
    )
    pin = write(root / "PLAN.json", value)
    write(root / "PLAN.sha256", (pin + "\n").encode())
    return {
        "plan_sha256": pin,
        "revision": REVISION,
        "counts": COUNTS,
        "download_bytes": sum(v["bytes"] for v in files.values()),
    }


def read_plan(root):
    raw = (root / "PLAN.json").read_bytes()
    pin = (root / "PLAN.sha256").read_text().strip()
    require(sha(raw) == pin, "plan changed")
    value = json.loads(raw)
    require(
        value["schema"] == "perc1.cord-source-plan.v1"
        and value["revision"] == REVISION
        and value["counts"] == COUNTS
        and value["indices"] == {s: list(range(n)) for s, n in COUNTS.items()},
        "fixed sampling plan changed",
    )
    return value, pin


def download(root, attempt):
    root = Path(root)
    value, plan_pin = read_plan(root)
    require(
        attempt.isascii() and attempt.isalnum() and len(attempt) <= 32,
        "invalid attempt ID",
    )
    directory = root / ("download-" + attempt)
    directory.mkdir(mode=0o700)

    def one(split):
        spec, started = value["shards"][split], time.monotonic_ns()
        status = dict(split=split, plan_sha256=plan_pin, expected=spec, success=False)
        try:
            response, headers = request(
                f"https://huggingface.co/datasets/{DATASET}/resolve/{REVISION}/{spec['path']}"
            )
            write(directory / (split + "-headers.json"), headers)
            with response, (directory / (split + ".parquet")).open("xb") as stream:
                size, checksum = 0, hashlib.sha256()
                while block := response.read(1024 * 1024):
                    size += len(block)
                    require(size <= spec["bytes"], "download exceeds frozen size")
                    stream.write(block)
                    checksum.update(block)
            status.update(bytes=size, sha256=checksum.hexdigest())
            require(
                size == spec["bytes"] and checksum.hexdigest() == spec["sha256"],
                "original shard size/hash mismatch",
            )
            status["success"] = True
        except Exception as error:
            status["error"] = {
                "type": type(error).__name__,
                "message": str(error)[:500],
            }
        status["wall_ns"] = time.monotonic_ns() - started
        write(directory / (split + "-receipt.json"), status)
        return status

    with ThreadPoolExecutor(max_workers=3) as pool:
        results = list(pool.map(one, COUNTS))
    summary = dict(
        plan_sha256=plan_pin,
        success=all(v["success"] for v in results),
        splits=[{k: v[k] for k in ("split", "success", "wall_ns")} for v in results],
    )
    write(directory / "SUMMARY.json", summary)
    return summary


def extract(root, attempt):
    import io
    import pyarrow.parquet as parquet
    from PIL import Image

    root = Path(root)
    value, plan_pin = read_plan(root)
    source = root / ("download-" + attempt)
    require(
        json.loads((source / "SUMMARY.json").read_bytes())["success"] is True,
        "incomplete shard download",
    )
    actor, evaluator = root / "actor", root / "evaluator"
    actor.mkdir(mode=0o700)
    evaluator.mkdir(mode=0o700)
    public, sealed, failures = [], [], []
    for split, count in COUNTS.items():
        shard = source / (split + ".parquet")
        require(
            file_sha(shard) == value["shards"][split]["sha256"],
            "shard changed before extraction",
        )
        table = parquet.read_table(shard, columns=["image", "ground_truth"]).slice(
            0, count
        )
        require(table.num_rows == count, "missing preregistered rows")
        (actor / split).mkdir()
        (evaluator / split).mkdir()
        for index, row in enumerate(table.to_pylist()):
            identity = f"cord-v2-{split}-{index:05d}"
            try:
                raw, label = row["image"]["bytes"], row["ground_truth"]
                require(
                    type(raw) is bytes and raw and type(label) is str,
                    "invalid embedded image/annotation",
                )
                with Image.open(io.BytesIO(raw)) as image:
                    image_format, dimensions = image.format, list(image.size)
                    image.load()
                image_path = f"{split}/{index:05d}.source"
                label_path = f"{split}/{index:05d}.json"
                image_sha = write(actor / image_path, raw)
                label_sha = write(evaluator / label_path, label.encode())
                public.append(
                    dict(
                        source_id=identity,
                        split=split,
                        row_index=index,
                        path=image_path,
                        sha256=image_sha,
                        bytes=len(raw),
                        format=image_format,
                        dimensions=dimensions,
                        exposed_before_plan=index
                        in value["exposed_before_plan"][split],
                        derivative_viewer_image=False,
                        original_capture_authenticated=False,
                        dataset_revision=REVISION,
                        shard_sha256=value["shards"][split]["sha256"],
                    )
                )
                sealed.append(
                    dict(
                        source_id=identity,
                        split=split,
                        row_index=index,
                        path=label_path,
                        sha256=label_sha,
                        bytes=len(label.encode()),
                    )
                )
            except Exception as error:
                failures.append(
                    dict(
                        source_id=identity,
                        error_type=type(error).__name__,
                        message=str(error)[:500],
                    )
                )
    write(
        actor / "SOURCES.json",
        dict(schema="perc1.cord-images.v1", plan_sha256=plan_pin, sources=public),
    )
    write(
        evaluator / "LABELS.json",
        dict(schema="perc1.cord-labels.v1", plan_sha256=plan_pin, labels=sealed),
    )
    summary = dict(
        schema="perc1.cord-materialization.v1",
        plan_sha256=plan_pin,
        success=not failures and len(public) == sum(COUNTS.values()),
        counts={s: sum(v["split"] == s for v in public) for s in COUNTS},
        image_bytes=sum(v["bytes"] for v in public),
        failures=failures,
        source_independence_verified=False,
        scientific_qualified=False,
        adoption="NoUpdate",
    )
    roles = dict(train="train", validation="dev", test="confirmation")
    index = []
    for image, annotation in zip(public, sealed):
        require(
            image["source_id"] == annotation["source_id"],
            "image/annotation index changed",
        )
        index.append(
            dict(
                id=image["source_id"],
                split=roles[image["split"]],
                dataset_split=image["split"],
                row_index=image["row_index"],
                image_path=str((actor / image["path"]).absolute()),
                image_sha256=image["sha256"],
                annotation_path=str((evaluator / annotation["path"]).absolute()),
                annotation_sha256=annotation["sha256"],
                exposed_before_plan=image["exposed_before_plan"],
            )
        )
    write(
        root / "INDEX.json",
        dict(
            schema="perc1.cord-index.v1",
            revision=REVISION,
            plan_sha256=plan_pin,
            success=summary["success"],
            sources=index,
        ),
    )
    write(root / "MATERIALIZATION.json", summary)
    return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("plan", "download", "extract"))
    parser.add_argument("--root", required=True)
    parser.add_argument("--attempt", default="001")
    args = parser.parse_args()
    result = (
        plan(args.root)
        if args.mode == "plan"
        else download(args.root, args.attempt)
        if args.mode == "download"
        else extract(args.root, args.attempt)
    )
    print(json.dumps(result, sort_keys=True))
    raise SystemExit(0 if result.get("success", True) else 1)
