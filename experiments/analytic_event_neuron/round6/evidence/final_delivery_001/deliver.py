from pathlib import Path, PurePosixPath
import datetime, hashlib, json, os, posixpath, re, stat, sys, time, traceback, urllib.parse, zipfile

COMMIT = "3d037bf23bf33eaedceaef0cee9835981ae97156"
REPO = Path("/dev/shm/hepta-round6-d831a963ef2f/hepta-analytic")
ROUND = "experiments/analytic_event_neuron/round6"
R6 = REPO / ROUND
ROOT = Path("/dev/shm/hepta-round6-d831a963ef2f/final_delivery_001")
DELIVERY = Path("/workspace/scratch/d831a963ef2f/deliverables")
BUNDLE = Path("/workspace/scratch/d831a963ef2f/publication_queue/final_bundle_001")
EXPECTED_MANIFEST = "539d5b59740faeb3e96f68428d7af093e48ec47156e14de2ab0b346e16426bfc"
EXPECTED_INDEX = "ab6265091254e1ed74b896602e3156dabb0d21900dcec54e296a84fed4f0e2b3"
EXPECTED_REPORT = "3da96f337bff2abbe80645ec8ecf01295b4dc3fd40c974647198e61c2c689e88"
EXPECTED_GUIDE = "8a74b89b1e3e830bae9f5bed49281f14bfe936935939b109d9e42125911f4cb3"
EXPECTED_HELPER = "3c98bfe234c1bfba14b72e114f771cd18c06fc900d754be3c59d3145a12cbb66"
EXPECTED_IMAGE = "f2df5da20cbc1c9fcc99f402dd96ded07accccbbe5c3afa838a717b9dd85f014"
ARCHIVE_SHA = "2a1b985439029ada9eb3493a6f2cb6d51d204fe051ef2327e9e7d2ef397e5336"
START = datetime.datetime.now(datetime.timezone.utc).isoformat()
WALL = time.perf_counter_ns()
CPU = time.process_time_ns()


def require(condition, message):
    if not condition:
        raise ValueError(message)


def sha(path):
    result = hashlib.sha256()
    with Path(path).open("rb") as stream:
        while block := stream.read(1024 * 1024):
            result.update(block)
    return result.hexdigest()


def save_json(path, value):
    with Path(path).open("x") as stream:
        json.dump(value, stream, sort_keys=True, ensure_ascii=False, indent=2)
        stream.write("\n")


def safe_name(name):
    p = PurePosixPath(name)
    require(bool(name) and not p.is_absolute() and "\\" not in name and
            all(part not in ("", ".", "..") for part in name.split("/")), "Unsafe member name")
    require(str(p) == name, "Noncanonical member name")
    return name


def free_bytes(path):
    value = os.statvfs(path)
    return value.f_bavail * value.f_frsize


def main():
    free_before = free_bytes(DELIVERY)
    require(free_before >= 500_000_000, "Insufficient free space for the one outer ZIP")
    manifest_path = BUNDLE / "BUNDLE.json"
    index_path = DELIVERY / "FINAL_PUBLICATION.json"
    require(sha(manifest_path) == EXPECTED_MANIFEST, "Final manifest differs")
    require(sha(index_path) == EXPECTED_INDEX, "Final publication index differs")
    manifest = json.loads(manifest_path.read_text())
    index = json.loads(index_path.read_text())
    require(index["manifest_sha256"] == EXPECTED_MANIFEST, "Publication manifest binding differs")
    require(index["bundle_path"] == ROUND + "/evidence/final_bundle_001", "Publication path differs")
    require(manifest["archive"]["sha256"] == ARCHIVE_SHA and manifest["archive"]["bytes"] == 354658019,
            "Archive identity differs")
    parts = manifest["parts"]
    require(len(parts) == 451 and len(manifest["members"]) == 1253, "Unexpected sealed bundle counts")
    part_names = [part["name"] for part in parts]
    require(part_names == [f"part-{i:05d}.bin" for i in range(451)], "Part sequence differs")
    require({path.name for path in BUNDLE.iterdir()} == {"BUNDLE.json", *part_names}, "Queue has extra or missing entries")
    member_index = {member["name"]: member for member in manifest["members"]}
    require(len(member_index) == len(manifest["members"]), "Duplicate sealed member names")
    sources = {
        "REPORT.md": (R6 / "REPORT.md", EXPECTED_REPORT),
        "REPRODUCE.md": (R6 / "REPRODUCE.md", EXPECTED_GUIDE),
        "artifact_bundle.py": (R6 / "artifact_bundle.py", EXPECTED_HELPER),
        "utility_and_calibration.png": (DELIVERY / "utility_and_calibration.png", EXPECTED_IMAGE),
    }
    for name, (path, expected) in sources.items():
        require(path.is_file() and not path.is_symlink() and sha(path) == expected, "Input differs: " + name)
    for name in ("REPORT.md", "REPRODUCE.md", "artifact_bundle.py"):
        require(member_index[ROUND + "/" + name]["sha256"] == sources[name][1], "Sealed source differs")
    require(member_index[ROUND + "/evidence/figures_registered_001/utility_and_calibration.png"]["sha256"] == EXPECTED_IMAGE,
            "Sealed image differs")

    original = (R6 / "REPORT.md").read_bytes().decode("utf-8")
    mapping = []

    def evidence_url(target):
        relative = posixpath.normpath(posixpath.join(ROUND, target))
        safe_name(relative)
        path = REPO / relative
        require(path.is_file() and not path.is_symlink(), "Missing linked evidence: " + relative)
        digest = sha(path)
        require(member_index[relative]["sha256"] == digest, "Linked evidence differs from seal")
        url = "https://github.com/TrillionniumFoundation/hepta-private-ci/blob/" + COMMIT + "/" + urllib.parse.quote(relative, safe="/")
        return relative, url, digest

    definition = re.compile(r"^(\[([^\]]+)\]:[ \t]+)(\S+)([^\n]*)$", re.M)
    old_definitions = {}

    def replace_definition(match):
        prefix, label, target, suffix = match.groups()
        old_definitions[label] = target
        if urllib.parse.urlsplit(target).scheme or target.startswith("#"):
            return match.group(0)
        relative, url, digest = evidence_url(target)
        mapping.append({"kind": "reference", "label": label, "original": target, "portable": url,
                        "repository_path": relative, "sealed_member_sha256": digest})
        return prefix + url + suffix

    portable = definition.sub(replace_definition, original)
    image_pattern = re.compile(r"!\[([^\]]*)\]\(([^)]+)\)")
    images = list(image_pattern.finditer(portable))
    require(len(images) == 1 and images[0].group(2) == "evidence/figures_registered_001/utility_and_calibration.png", "Unexpected image layout")
    image_original = images[0].group(2)
    portable = image_pattern.sub(lambda match: "![" + match.group(1) + "](utility_and_calibration.png)", portable)
    mapping.append({"kind": "image", "original": image_original, "portable": "utility_and_calibration.png", "sha256": EXPECTED_IMAGE})
    original_note = "本报告的本地证据链接均相对于本文件所在的 `round6` 目录。"
    portable_note = "本便携版的证据链接固定到 GitHub 提交 `" + COMMIT + "`；图像从同包的 `utility_and_calibration.png` 读取。"
    require(portable.count(original_note) == 1, "Unexpected portability note")
    portable = portable.replace(original_note, portable_note)
    reversed_text = definition.sub(lambda match: match.group(1) + old_definitions[match.group(2)] + match.group(4), portable)
    reversed_text = image_pattern.sub(lambda match: "![" + match.group(1) + "](" + image_original + ")", reversed_text)
    reversed_text = reversed_text.replace(portable_note, original_note)
    require(reversed_text == original, "Scientific body or other report text changed")
    require(len([item for item in mapping if item["kind"] == "reference"]) == 66, "Unexpected reference count")
    portable_path = DELIVERY / "HEPTA_ROUND6_REPORT.md"
    with portable_path.open("xb") as stream:
        stream.write(portable.encode("utf-8"))

    readme = f'''HEPTA ROUND6 — 封存研究交付包

发布控制提交: {COMMIT}
BUNDLE.json SHA256: {EXPECTED_MANIFEST}
FINAL_PUBLICATION.json SHA256: {EXPECTED_INDEX}

本 ZIP 包含:
  HEPTA_ROUND6_REPORT.md           中文完整验收报告（证据链接固定到上述提交）
  utility_and_calibration.png     报告图表，可离线显示
  REPRODUCE.md                    完整复现指南与固定结果/审计身份
  artifact_bundle.py              标准库校验和恢复工具
  FINAL_PUBLICATION.json          外部发布、远端回读和恢复索引
  final_bundle_001/BUNDLE.json    内层封存证据清单
  final_bundle_001/part-*.bin      全部 451 个原始二进制分片

外层 ZIP 不再重复保存 archive.tar.gz。分片已经是完整压缩归档的连续字节。
恢复后直接得到部分研究仓库根目录，其中包含完整研究证据与继承源码；
它不是全历史 Git 仓库，也不包含完整 codex-rs 构建工作区。

解压 ZIP 到新目录后，在包含本 README.txt 的目录中执行以下 Bash 命令。
将第一行替换成实际解压目录的绝对路径。Python 工具只需标准库；这里不训练模型。

  cd /absolute/path/to/extracted/HEPTA_ROUND6_BUNDLE
  python -B artifact_bundle.py verify final_bundle_001 \\
    --expected-manifest-sha256 {EXPECTED_MANIFEST}
  hepta_final_parent=$(mktemp -d -t hepta-round6-final.XXXXXX)
  python -B artifact_bundle.py restore final_bundle_001 "$hepta_final_parent/research" \\
    --expected-manifest-sha256 {EXPECTED_MANIFEST}

目标 research 必须尚不存在。工具校验全部分片、完整归档和成员后才创建恢复目录，
然后回读成员并保留可执行权限。分片目录旁需要归档重组的临时空间。
完整恢复目标为 "$hepta_final_parent/research"，无额外 hepta-analytic 外层目录。

在记录的数值环境中，再执行指南中的精确冻结验证（不会重训）:

  cd "$hepta_final_parent/research"
  hepta_python=/opt/codex/runtimes/codex-primary-runtime/dependencies/python/bin/python
  "$hepta_python" -B -m experiments.analytic_event_neuron.round6.lifecycle verify \\
    --run-dir experiments/analytic_event_neuron/round6/evidence/registered_001 \\
    --expected-freeze-sha256 1f4d994da28d3bd61853a904d3e9da03b6ea6c90fe9d680e217f976656450ca1

数值环境与历史 native 二进制身份详见 REPRODUCE.md；不同环境可以进行字节验真，
但不能宣称通过原始环境的精确 lifecycle 验证。改变训练、种子或环境属于新实验身份。
GitHub 证据链接需要相应私有仓库读取权限；恢复后的对应本地文件可直接查看。

本轮确认与独立审计已完成；两项预登记主要收益优越性门槛均未通过。
运行时证据限于本地研究 owner、已登记的恢复范围和实际测量环境，未激活生产 Agentd。
无需重新训练即可阅读和验证这批不可变证据。外层 ZIP 自身的校验收据单独发布，
不放入 ZIP 内，以避免自哈希循环。
'''
    readme_path = DELIVERY / "README.txt"
    with readme_path.open("x") as stream:
        stream.write(readme)
    mapping_record = {"schema": "hepta.round6.portable-report-map.v1", "control_commit": COMMIT,
        "source_report_sha256": EXPECTED_REPORT, "portable_report_sha256": sha(portable_path),
        "scientific_body_preserved": True, "reverse_transform_equals_source": True,
        "layout_note": {"original": original_note, "portable": portable_note}, "mappings": mapping,
        "url_targets_bound_to_sealed_local_members": True, "remote_urls_individually_requested_by_this_packager": False}
    save_json(ROOT / "PORTABLE_REPORT_MAP.json", mapping_record)

    inputs = {
        "artifact_bundle.py": R6 / "artifact_bundle.py", "REPRODUCE.md": R6 / "REPRODUCE.md",
        "FINAL_PUBLICATION.json": index_path, "HEPTA_ROUND6_REPORT.md": portable_path,
        "utility_and_calibration.png": DELIVERY / "utility_and_calibration.png", "README.txt": readme_path,
        "final_bundle_001/BUNDLE.json": manifest_path,
    }
    for part in parts:
        safe_name(part["name"])
        require(1 <= part["bytes"] <= 786432, "Invalid part size")
        inputs["final_bundle_001/" + part["name"]] = BUNDLE / part["name"]
    require(len(inputs) == 458, "Unexpected ZIP file count")
    part_index = {"final_bundle_001/" + part["name"]: part for part in parts}
    expected_members = {}
    for name, path in inputs.items():
        safe_name(name)
        require(path.is_file() and not path.is_symlink(), "Nonregular ZIP input")
        metadata = path.stat()
        part = part_index.get(name)
        expected_members[name] = {"bytes": metadata.st_size, "mode": stat.S_IMODE(metadata.st_mode),
            "sha256": part["sha256"] if part else sha(path)}
        if part:
            require(metadata.st_size == part["bytes"], "Part size differs")
            expected_members[name]["git_blob_sha1"] = part["git_blob_sha1"]
    destination = DELIVERY / "HEPTA_ROUND6_BUNDLE.zip"
    temporary = DELIVERY / "HEPTA_ROUND6_BUNDLE.zip.partial"
    require(not destination.exists() and not temporary.exists(), "ZIP output already exists")
    with zipfile.ZipFile(temporary, "x", compression=zipfile.ZIP_STORED, allowZip64=True) as archive:
        for name in sorted(inputs):
            info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            info.create_system = 3
            info.compress_type = zipfile.ZIP_STORED
            info.external_attr = (stat.S_IFREG | expected_members[name]["mode"]) << 16
            with inputs[name].open("rb") as source, archive.open(info, "w") as output:
                while block := source.read(1024 * 1024):
                    output.write(block)
    archive_digest = hashlib.sha256()
    archive_bytes = 0
    with zipfile.ZipFile(temporary, "r") as archive:
        infos = archive.infolist()
        require([info.filename for info in infos] == sorted(inputs), "ZIP names/order differ or duplicate")
        for info in infos:
            name = safe_name(info.filename)
            require(not info.is_dir() and stat.S_ISREG(info.external_attr >> 16), "Unexpected ZIP member type")
            require(stat.S_IMODE(info.external_attr >> 16) == expected_members[name]["mode"], "ZIP mode differs")
            digest = hashlib.sha256()
            length = 0
            part = part_index.get(name)
            git = hashlib.sha1(b"blob " + str(part["bytes"]).encode() + b"\0") if part else None
            with archive.open(info) as stream:
                while block := stream.read(1024 * 1024):
                    digest.update(block); length += len(block)
                    if part:
                        git.update(block); archive_digest.update(block); archive_bytes += len(block)
            require(length == expected_members[name]["bytes"] and digest.hexdigest() == expected_members[name]["sha256"], "ZIP member content differs: " + name)
            if part:
                require(git.hexdigest() == part["git_blob_sha1"], "ZIP part Git blob identity differs")
    require(archive_bytes == manifest["archive"]["bytes"] and archive_digest.hexdigest() == ARCHIVE_SHA, "Concatenated ZIP archive identity differs")
    require(all("archive.tar.gz" not in name for name in inputs), "Duplicate full archive included")
    for name, (path, expected) in sources.items():
        require(sha(path) == expected, "Sealed/read-only source changed: " + name)
    require(sha(index_path) == EXPECTED_INDEX and sha(manifest_path) == EXPECTED_MANIFEST, "Index/manifest changed")
    os.link(temporary, destination)
    temporary.unlink()
    save_json(ROOT / "ZIP_MEMBERS.json", {"schema": "hepta.round6.zip-member-checks.v1", "members": expected_members,
        "all_names_sizes_modes_sha256_checked": True, "all_part_git_blob_sha1_checked": True,
        "archive": {"bytes": archive_bytes, "sha256": archive_digest.hexdigest()}, "zip_read_crc_checked": True})
    result = {"schema": "hepta.round6.user-delivery.v1", "started_utc": START,
        "completed_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(), "passed": True,
        "publication_control_commit": COMMIT, "data_commit": "f6c5594cd1c183578eb68da7bf20613ce9723e26",
        "zip": {"path": str(destination), "bytes": destination.stat().st_size, "sha256": sha(destination),
            "files": len(inputs), "compression": "ZIP_STORED; raw parts already contain gzip bytes"},
        "bundle_manifest_sha256": EXPECTED_MANIFEST, "bundle_parts": len(parts), "sealed_members": len(manifest["members"]),
        "concatenated_archive": {"bytes": archive_bytes, "sha256": archive_digest.hexdigest()},
        "publication_index_sha256": EXPECTED_INDEX, "source_report_sha256": EXPECTED_REPORT,
        "portable_report": {"path": str(portable_path), "bytes": portable_path.stat().st_size, "sha256": sha(portable_path)},
        "readme": {"path": str(readme_path), "bytes": readme_path.stat().st_size, "sha256": sha(readme_path)},
        "reproduce_sha256": EXPECTED_GUIDE, "helper_sha256": EXPECTED_HELPER, "image_sha256": EXPECTED_IMAGE,
        "map_sha256": sha(ROOT / "PORTABLE_REPORT_MAP.json"), "members_receipt_sha256": sha(ROOT / "ZIP_MEMBERS.json"),
        "packager_source_sha256": sha(Path(__file__)), "source_package_unchanged": True,
        "new_scientific_execution": False, "archive_restoration_performed": False,
        "full_archive_duplicate_in_zip": False, "receipt_inside_zip": False,
        "overlay_free_before_bytes": free_before, "overlay_free_after_bytes": free_bytes(DELIVERY),
        "wall_ns": time.perf_counter_ns() - WALL, "parent_cpu_ns": time.process_time_ns() - CPU}
    save_json(ROOT / "RECEIPT.json", result)
    output = {"receipt": str(ROOT / "RECEIPT.json"), "receipt_sha256": sha(ROOT / "RECEIPT.json"), **result}
    with (ROOT / "STDOUT.txt").open("x") as stream:
        stream.write(json.dumps(output, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(output, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    try:
        save_json(ROOT / "COMMAND.json", {"argv": [sys.executable, "-B", str(Path(__file__))], "cwd": str(Path.cwd())})
        main()
    except Exception as error:
        save_json(ROOT / "FAILURE.json", {"passed": False, "error_type": type(error).__name__, "error": str(error),
            "traceback": traceback.format_exc(), "started_utc": START, "wall_ns": time.perf_counter_ns() - WALL})
        raise
