"""Source-exact, answer-blind first-parent diff review packet (research only).

This verifies an immutable GitHub Actions source archive, not human semantics.
It never runs source code, opens model gold/answers, or claims complete PR diffs.
"""

from collections import Counter
import argparse
import difflib
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import stat
import zipfile

ORIGINAL_ZIP_SHA256 = "0dd31ed0101c0125ee2c5f9ffe82ae71d083dcf4a00206eb65fdcc7cf75959e3"
SOURCE_MANIFEST_SHA256 = (
    "ef2a46ce037db4a91affddd2498eb8e089771ae5734bc13c56cb8a97b840a463"
)
SOURCE_COMMIT = "92ef1d2c2522ec79964c47f5d493b5b6250cd4bd"
PROFILE = "hepta.memorycell.real-project.first-parent-review-lines.v1"
MAX_REVIEW_LINES = 80
MAX_REVIEW_BYTES = 6000
STATUSES = frozenset(
    (
        "byte-different-versus-first-parent",
        "added-at-first-parent-step",
        "unchanged-versus-first-parent",
        "added-already-present-in-first-parent",
        "ambiguous-multi-parent-head",
        "unresolved-renamed-previous-path",
    )
)
SHA40 = re.compile(r"[a-f0-9]{40}\Z")
SHA64 = re.compile(r"[a-f0-9]{64}\Z")


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def git_blob(raw):
    return hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest()


def unique_json(data):
    def reject_pairs(items):
        out = {}
        for key, value in items:
            if key in out:
                raise ValueError("duplicate source JSON key")
            out[key] = value
        return out

    def reject_constant(value):
        raise ValueError("nonfinite source JSON")

    return json.loads(
        data, object_pairs_hook=reject_pairs, parse_constant=reject_constant
    )


def checked_archive(path):
    """Require original outer pin, *all* 142 inner hashes, no unsafe ZIP entries."""
    path = Path(path)
    if (
        path.is_symlink()
        or not path.is_file()
        or not 0 < path.stat().st_size < 4 * 1024 * 1024
    ):
        raise ValueError("bounded regular source ZIP required")
    if sha(path.read_bytes()) != ORIGINAL_ZIP_SHA256:
        raise ValueError("externally pinned source ZIP mismatch")
    with zipfile.ZipFile(path) as archive:
        infos = archive.infolist()
        if len(infos) != 143 or sum(x.file_size for x in infos) > 16 * 1024 * 1024:
            raise ValueError("complete original source archive census required")
        content = {}
        for entry in infos:
            name = PurePosixPath(entry.filename)
            if (
                name.is_absolute()
                or ".." in name.parts
                or "\\" in entry.filename
                or entry.is_dir()
                or stat.S_ISLNK(entry.external_attr >> 16)
                or entry.filename in content
                or str(name) != entry.filename
            ):
                raise ValueError("unsafe or duplicate original ZIP entry")
            content[entry.filename] = archive.read(entry)
    raw_manifest = content.get("SHA256SUMS", b"")
    pins = {}
    for line in raw_manifest.decode("ascii").splitlines():
        match = re.fullmatch(r"([a-f0-9]{64})  (?:\./)?(.+)", line)
        if match is None or match.group(2) in pins:
            raise ValueError("ambiguous complete source manifest")
        pins[match.group(2)] = match.group(1)
    if set(pins) != set(content) - {"SHA256SUMS"}:
        raise ValueError("missing original SHA manifest entry")
    for name, expected in pins.items():
        if sha(content[name]) != expected:
            raise ValueError("replaced original source bytes: " + name)
    if content.get("tested-commit.txt", b"").strip().decode() != SOURCE_COMMIT:
        raise ValueError("original generating commit drift")
    return content


def replay_source(content, name, *, git_sha, digest):
    if not isinstance(name, str) or not name.startswith(
        ("original/blobs/", "first-parent/before-blobs/")
    ):
        raise ValueError("unregistered Git source path")
    if not SHA40.fullmatch(git_sha) or not SHA64.fullmatch(digest):
        raise ValueError("unbound original source hashes")
    raw = content.get(name)
    if raw is None or not name.endswith(git_sha + ".blob"):
        raise ValueError("missing exact original code bytes")
    if git_blob(raw) != git_sha or sha(raw) != digest:
        raise ValueError("original Git SHA-1 / raw SHA-256 changed")
    return raw


def diff_lines(
    before, after, path, *, max_lines=MAX_REVIEW_LINES, max_bytes=MAX_REVIEW_BYTES
):
    """Bounded UTF-8 ONLY preview; never silently replace invalid source bytes."""
    if (
        type(max_lines) is not int
        or not 1 <= max_lines <= 400
        or type(max_bytes) is not int
        or not 64 <= max_bytes <= 20000
    ):
        raise ValueError("bounded excerpt budget required")
    try:
        previous = before.decode("utf-8", errors="strict").splitlines(keepends=True)
        current = after.decode("utf-8", errors="strict").splitlines(keepends=True)
    except UnicodeDecodeError:
        return dict(
            state="unavailable-non-utf8",
            text=None,
            truncated=False,
            preview_sha256=None,
            shown_lines=0,
            preview_is_complete=False,
        )
    emitted = []
    used = 0
    lines = 0
    truncated = False
    for line in difflib.unified_diff(
        previous,
        current,
        fromfile="before/" + path,
        tofile="head/" + path,
        n=2,
        lineterm="\n",
    ):
        b = line.encode("utf-8")
        if lines == max_lines or used + len(b) > max_bytes:
            truncated = True
            break
        emitted.append(line)
        lines += 1
        used += len(b)
    text = "".join(emitted)
    return dict(
        state="source-exact-unified-first-parent",
        text=text,
        truncated=truncated,
        preview_sha256=sha(text.encode("utf-8")),
        shown_lines=lines,
        preview_is_complete=not truncated,
    )


def assemble(content):
    """Compile 16 real PR source-first questions; none receives a verdict."""

    def obj(name):
        return unique_json(content[name])

    original_ready = obj("original/READY.json")
    before_ready = obj("first-parent/READY.json")
    merge_ready = obj("merge-concordance/READY.json")
    inventory = obj("original/inventory.json")
    context = obj("first-parent/context.json")
    packet = obj("unsigned-first-parent-review.json")
    if (
        original_ready.get("original_file_bindings") != 80
        or original_ready.get("original_byte_count") != 6503104
        or original_ready.get("source_manifest_sha256") != SOURCE_MANIFEST_SHA256
        or original_ready.get("production_accepted") is not False
        or before_ready.get("original_file_count") != 80
        or before_ready.get("original_source_manifest_sha256") != SOURCE_MANIFEST_SHA256
        or before_ready.get("complete_pr_diff_certified") is not False
        or merge_ready.get("merge_file_count") != 31
        or merge_ready.get("common_previous_files") != 0
        or merge_ready.get("production_accepted") is not False
        or context.get("source_cut_utc") != packet.get("source_cut_utc")
        or context.get("original_source_manifest_sha256") != SOURCE_MANIFEST_SHA256
        or packet.get("source_manifest_sha256") != SOURCE_MANIFEST_SHA256
        or packet.get("independent_review_performed") is not False
        or packet.get("model_calls") != 0
        or packet.get("production_accepted") is not False
    ):
        raise ValueError("not the exact unreviewed original 80-file source cut")
    originals = inventory["originals"]
    parents = context["files"]
    questions = packet["questions"]
    if len(originals) != 80 or len(parents) != 80 or len(questions) != 16:
        raise ValueError("complete original file/question census required")
    source_keys = [
        (r["project"], r["pull_number"], r["head_sha"], r["path"]) for r in originals
    ]
    parent_keys = [
        (r["project"], r["pull_number"], r["head_sha"], r["original_path"])
        for r in parents
    ]
    if source_keys != parent_keys or len(set(source_keys)) != 80:
        raise ValueError("original/parent order or file identity drift")
    verified, statuses, preview_by_key = {}, Counter(), {}
    for original, parent in zip(originals, parents, strict=True):
        key = (
            original["project"],
            original["pull_number"],
            original["head_sha"],
            original["path"],
        )
        state = parent["comparison_status"]
        if (
            state not in STATUSES
            or parent["partition"] != original["partition"]
            or parent["original_head_sha1"] != original["blob_sha"]
            or parent["original_head_sha256"] != original["sha256"]
            or parent["full_pr_base_diff_certified"] is not False
            or parent["human_semantic_review_performed"] is not False
            or parent["independent_source_sufficiency"] is not None
        ):
            raise ValueError("first-parent provenance or review authority drift")
        head = replay_source(
            content,
            "original/" + original["blob_path"],
            git_sha=original["blob_sha"],
            digest=original["sha256"],
        )
        if len(head) != original["bytes"]:
            raise ValueError("original source length changed")
        prior, comparison = None, None
        if state == "byte-different-versus-first-parent":
            prior = replay_source(
                content,
                "first-parent/" + parent["before_blob_path"],
                git_sha=parent["previous_git_blob_sha1"],
                digest=parent["previous_sha256"],
            )
            if prior == head:
                raise ValueError("claimed changed parent source is identical")
            comparison = diff_lines(prior, head, original["path"])
        elif state == "added-at-first-parent-step":
            if parent["before_blob_path"] is not None:
                raise ValueError("added source has invented first-parent bytes")
            comparison = diff_lines(b"", head, original["path"])
        else:
            if parent["before_blob_path"] is not None:
                raise ValueError(
                    "unresolved source cannot provide asserted previous bytes"
                )
        statuses[state] += 1
        verified[key] = dict(
            source_path=original["path"],
            head_git_blob_sha1=original["blob_sha"],
            head_sha256=original["sha256"],
            parent_classification=state,
            previous_git_blob_sha1=parent["previous_git_blob_sha1"],
            previous_sha256=parent["previous_sha256"],
            diff=comparison,
            complete_pr_diff_certified=False,
            semantic_sufficiency_verified=False,
        )
        preview_by_key[key] = comparison
    if dict(statuses) != context["comparison_counts"] or len(verified) != 80:
        raise ValueError("file class census changed")
    if sum(x is not None for x in preview_by_key.values()) != 27:
        raise ValueError("registered changed/added diff preview census changed")
    cases, seen = [], set()
    for question in questions:
        qid = question["task_id"]
        if (
            not isinstance(qid, str)
            or not qid
            or qid in seen
            or question["answer_gold"] is not None
            or question["reviewer_verdict"] != "unreviewed"
            or question["source_sufficiency"] != "unknown"
            or question["answer_or_model_prediction_in_packet"] is not False
            or question["decoded_parent_diff_available"] is not False
            or question["historical_review_discussion_authenticated"] is not False
        ):
            raise ValueError("review case contaminated by answer or verdict")
        seen.add(qid)
        proj, pr, head = (
            question["source_project"],
            question["source_pr"],
            question["source_head_sha"],
        )
        expected = [key for key in source_keys if key[:3] == (proj, pr, head)]
        docs = question["verified_first_parent_files"]
        if len(docs) != len(expected) or [entry["original_path"] for entry in docs] != [
            key[3] for key in expected
        ]:
            raise ValueError("review evidence sources altered")
        files = []
        for key, bound in zip(expected, docs, strict=True):
            item = verified[key]
            if (
                bound["comparison_status"] != item["parent_classification"]
                or bound["head_git_blob_sha1"] != item["head_git_blob_sha1"]
                or bound["previous_git_blob_sha1"] != item["previous_git_blob_sha1"]
                or bound["previous_byte_sha256"] != item["previous_sha256"]
                or bound["semantic_sufficiency"] is not None
                or bound["complete_pr_diff_certified"] is not False
            ):
                raise ValueError("unsigned review bound to different original code")
            files.append(item)
        statuses_for_case = Counter(x["parent_classification"] for x in files)
        eligible = sum(x["diff"] is not None for x in files)
        cases.append(
            dict(
                task_id=qid,
                partition=question["partition"],
                project=proj,
                pull_number=pr,
                head_sha=head,
                question=question["question"],
                files=files,
                first_parent_preview_files=eligible,
                unresolved_file_count=len(files) - eligible,
                source_preview_sufficient_for_answer=None,
                human_reviewer_verdict=None,
                full_pr_diff_certified=False,
                no_model_answer_available=True,
            )
        )
    if len(cases) != 16 or len({x["project"] for x in cases}) != 4:
        raise ValueError("review source question or project family census changed")
    return dict(
        schema=PROFILE,
        original_generating_commit=SOURCE_COMMIT,
        original_source_zip_sha256=ORIGINAL_ZIP_SHA256,
        original_source_manifest_sha256=SOURCE_MANIFEST_SHA256,
        source_cut_utc=context["source_cut_utc"],
        source_original_file_count=80,
        questions_count=16,
        project_labels_count=4,
        comparison_counts=dict(statuses),
        context_bytes_verified=6503104,
        diff_preview_file_count=27,
        preview_line_budget=MAX_REVIEW_LINES,
        preview_byte_budget=MAX_REVIEW_BYTES,
        all_review_answers_withheld=True,
        reviewer_identity_authenticated=False,
        independent_semantic_review=False,
        historical_pr_discussion_authenticated=False,
        full_pr_base_diff_certified=False,
        complete_source_sufficiency_verified=False,
        independent_source_family_effective_n=None,
        actual_reader_model_calls=0,
        production_accepted=False,
        parametric_memory_training_qualified=False,
        cases=cases,
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source_zip", type=Path)
    parser.add_argument("output", type=Path)
    options = parser.parse_args()
    source = checked_archive(options.source_zip)
    report = assemble(source)
    with options.output.open("x", encoding="utf-8") as f:
        json.dump(
            report, f, indent=2, ensure_ascii=False, allow_nan=False, sort_keys=True
        )
        f.write("\n")
    print(
        json.dumps(
            {key: value for key, value in report.items() if key != "cases"},
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
