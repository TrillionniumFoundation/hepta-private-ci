"""Real Git-blob source-to-Reader capacity probe (research only).

All source bytes come from the exact six-project, two-process GitHub Actions
archive closure. The questions are mechanical function-declaration lookups, NOT
human certified semantic sufficiency, unseen benchmark tasks, or real program
execution. Source, task construction and retrieval are immutable before inference.
A frozen reference Reader is an axis, never credit for learned MemoryCells.
"""

from __future__ import annotations

import argparse
from collections import defaultdict
from dataclasses import asdict
import hashlib
import json
import os
from pathlib import Path
import re
import zipfile

SOURCE_SHA = "a4c7b9868461c11558546bd582796255cbca682c938a1704d62cd93a556406b4"
REOPEN_SHA = "59dee0a84099f6fb101dbfd5420c569f10c44a2d8a7b67c984e381edf4db9d36"
INVENTORY_SHA = "5ede9326e2234331f8f7f268a96257089a6703a74e7354206833db1d18f1beb0"
FROZEN_PLAN_SHA256 = "005025a81f40759dddd6576c21e3ef10114158e74456600ab5f4b0e39fef164b"
SOURCE_CUT = "2026-10-12T16:05:00Z"
EVALUATION = ("python/cpython", "scikit-learn/scikit-learn", "denoland/deno")
CONDITIONS = ("none", "hybrid_k4", "mechanical_support", "removed_declaration")
TIERS = ("smol-135m", "smol-1.7b")
SCHEMA = "hepta.memory.real-git-reader-function-probe.v1"
PROBE_COUNT_PER_REPO = 3
HEX40 = re.compile(r"[0-9a-f]{40}\Z")
HEX64 = re.compile(r"[0-9a-f]{64}\Z")
MARKER = re.compile(r"\s*(F\d{2})(?:\s*\[E[1-9][0-9]*\])*\s*\.?\s*\Z")
DECL = re.compile(
    r"^\s*(?:async\s+def|def|(?:pub(?:\([^)]*\))?\s+)?(?:async\s+)?fn)\s+"
    r"([A-Za-z_][A-Za-z_0-9]{7,})\s*\("
)


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def canonical(obj) -> bytes:
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def require(ok, why):
    if not ok:
        raise ValueError(why)


def strict_json(raw):
    def pairs(kvs):
        d = {}
        for k, v in kvs:
            require(k not in d, "duplicate JSON key")
            d[k] = v
        return d

    def bad_constant(v):
        raise ValueError("nonfinite JSON: " + v)

    return json.loads(raw, object_pairs_hook=pairs, parse_constant=bad_constant)


def verify_zip(path: Path, expected_hash: str, expected_members: int):
    require(path.is_file() and not path.is_symlink() and path.stat().st_size <= 8_000_000,
            "bounded regular original archive required")
    raw = path.read_bytes()
    require(digest(raw) == expected_hash, "external whole ZIP digest mismatch")
    with zipfile.ZipFile(path) as archive:
        infos = archive.infolist()
        names = [i.filename for i in infos]
        require(len(names) == expected_members + 1 and len(set(names)) == len(names)
                and set(names).issuperset({"SHA256SUMS"})
                and all(not n.startswith("/") and "\\" not in n and
                        all(p not in ("", ".", "..") for p in n.split("/"))
                        and len(n) < 320 for n in names), "unsafe ZIP members")
        require(all(i.file_size <= 1024 * 1024 and not i.is_dir() and
                    (i.flag_bits & 1) == 0 for i in infos), "unsafe ZIP member type")
        manifest = archive.read("SHA256SUMS").decode("utf-8").splitlines()
        checked = {}
        for line in manifest:
            fields = line.split(maxsplit=1)
            require(len(fields) == 2 and HEX64.fullmatch(fields[0]), "invalid ZIP manifest")
            member = fields[1].removeprefix("./")
            require(member in names and member != "SHA256SUMS" and member not in checked,
                    "unregistered/duplicate ZIP entry")
            data = archive.read(member)
            require(digest(data) == fields[0], "in-ZIP source hash mismatch")
            checked[member] = data
        require(len(checked) == expected_members and set(checked) == set(names) - {"SHA256SUMS"},
                "ZIP manifest incomplete")
        return checked


def real_source(source_zip: Path, reopen_zip: Path):
    archive = verify_zip(source_zip, SOURCE_SHA, 40)
    reopened = verify_zip(reopen_zip, REOPEN_SHA, 2)
    require(reopened.get("reopened-source-commit.txt", b"").strip() ==
            b"6ac55532cd3f65d02438cda7f642dc22afb107fe",
            "wrong original generation source for independent reopen")
    witness = strict_json(reopened["reopen.log"])
    require(witness.get("schema") == "hepta.memorycell.external-project-independent-reopen.v1"
            and witness.get("original_binary_reopen_completed") is True
            and witness.get("verified_original_byte_count") == 1558460
            and witness.get("verified_original_commit_objects") == 14
            and witness.get("verified_original_file_bindings") == 32
            and witness.get("independent_semantic_review") is False
            and witness.get("production_accepted") is False,
            "independent binary reopen did not complete")
    inventory_raw = archive["original/inventory.json"]
    require(digest(inventory_raw) == INVENTORY_SHA, "published exact source inventory drift")
    ready = strict_json(archive["original/READY.json"])
    inventory = strict_json(inventory_raw)
    require(ready.get("schema") == "hepta.memorycell.external-project-source-ready.v1"
            and ready.get("inventory_sha256") == INVENTORY_SHA
            and ready.get("verified_file_bindings") == 32
            and ready.get("verified_commit_objects") == 14
            and ready.get("verified_original_bytes") == 1558460
            and ready.get("independent_semantic_review") is False
            and ready.get("production_accepted") is False
            and inventory.get("source_cut_utc") == SOURCE_CUT
            and inventory.get("original_file_bindings") == 32
            and inventory.get("source_family_proxies") == 6
            and inventory.get("total_original_bytes") == 1558460
            and inventory.get("model_calls") == 0
            and inventory.get("independent_semantic_review") is False,
            "source-only closure lacks complete frozen cohort")
    files = inventory.get("files")
    require(isinstance(files, list) and len(files) == 32, "missing original file identities")
    roots, blobs, identities = set(), {}, set()
    for row in files:
        require(isinstance(row, dict) and row.get("repo") in {
            "python/cpython", "pandas-dev/pandas", "scikit-learn/scikit-learn",
            "tokio-rs/tokio", "prometheus/prometheus", "denoland/deno"
        } and row.get("partition") in ("train", "selection", "evaluation"),
            "unexpected Git source provenance")
        oid = row.get("blob_sha")
        require(isinstance(oid, str) and HEX40.fullmatch(oid) and
                (row["repo"], row["path"], oid) not in identities,
                "unbound or duplicate source file")
        identities.add((row["repo"], row["path"], oid))
        member = f"original/blobs/{oid}.blob"
        require(member in archive, "missing original immutable bytes")
        raw = archive[member]
        git_hash = hashlib.sha1(f"blob {len(raw)}\0".encode() + raw).hexdigest()
        require(oid == git_hash and digest(raw) == row["sha256"] and
                len(raw) == row["bytes"], "original Git blob differs from frozen SHA")
        blobs[(row["repo"], row["path"])] = raw
        roots.add(row["repo"])
    require(len(roots) == 6 and sum(len(x) for x in blobs.values()) == 1558460,
            "incomplete six-repository source population")
    return files, blobs


def declarations(text: str):
    rows = []
    for number, line in enumerate(text.splitlines()):
        matched = DECL.match(line)
        if matched and len(line) < 350:
            rows.append((matched[1], number))
    return rows


def excerpt(text: str, symbol: str):
    lines = text.splitlines()
    matches = [i for name, i in declarations(text) if name == symbol]
    require(len(matches) == 1, "ambiguous original declaration")
    at = matches[0]
    # Source detail is a query-derived window, not a generated/summarized fact.
    part = "\n".join(lines[max(0, at - 1): at + 5])[:1150]
    require(DECL.match(lines[at]) and symbol in part, "not an original declaration window")
    return part, at


def build_plan(files, blobs):
    """Deterministic; no gold labels are written to the public plan."""
    evaluation = sorted(
        [row for row in files if row["repo"] in EVALUATION and row["partition"] == "evaluation"
         and row["path"].endswith((".py", ".rs"))],
        key=lambda x: (x["repo"], x["path"]),
    )
    by_repo = defaultdict(list)
    file_texts = {}
    for row in evaluation:
        raw = blobs[(row["repo"], row["path"])]
        try:
            text = raw.decode("utf-8", "strict")
        except UnicodeError:
            continue
        file_texts[(row["repo"], row["path"])] = text
        by_repo[row["repo"]].append(row)
    require(set(by_repo) == set(EVALUATION), "missing distinct held-out project families")
    cases = []
    for repo in EVALUATION:
        docs = by_repo[repo]
        require(2 <= len(docs) <= 32, "insufficient bounded repository sources")
        markers = {row["path"]: f"F{i:02d}" for i, row in enumerate(docs, 1)}
        names = defaultdict(set)
        for row in docs:
            for symbol, at in declarations(file_texts[(repo, row["path"]) ]):
                if not symbol.startswith("test_") and not symbol.startswith("__"):
                    names[symbol].add(row["path"])
        possibilities = []
        for symbol, paths in names.items():
            if len(paths) != 1:
                continue
            path = next(iter(paths))
            text = file_texts[(repo, path)]
            if sum(1 for name, _ in declarations(text) if name == symbol) != 1:
                continue
            rank = digest((repo + "\0" + symbol).encode())
            possibilities.append((rank, symbol, path))
        possibilities.sort()
        picked, seen_paths = [], set()
        # Spread cases over distinct original source files where possible.
        for _, symbol, path in possibilities:
            if path not in seen_paths:
                picked.append((symbol, path))
                seen_paths.add(path)
            if len(picked) == PROBE_COUNT_PER_REPO:
                break
        for _, symbol, path in possibilities:
            if len(picked) == PROBE_COUNT_PER_REPO:
                break
            if (symbol, path) not in picked:
                picked.append((symbol, path))
        require(len(picked) == PROBE_COUNT_PER_REPO,
                "could not precommit equal probe census per project")
        for symbol, target_path in picked:
            # Retrieve over complete real files by source-key lexical occurrence;
            # no target marker is an argument of this retrieval function.
            ranked = sorted(docs, key=lambda row: (
                -len(re.findall(r"\b" + re.escape(symbol) + r"\b",
                                 file_texts[(repo, row["path"]) ])),
                row["blob_sha"],
            ))
            selected = ranked[:4]
            original = next(row for row in docs if row["path"] == target_path)
            needed, pos = excerpt(file_texts[(repo, target_path)], symbol)

            def entry(row, *, ablate=False):
                text = file_texts[(repo, row["path"])]
                # The prompt contains no generated summary, expected gold or
                # fabricated PR reasoning: only original code + file marker.
                if row["path"] == target_path:
                    source, _ = excerpt(text, symbol)
                    if ablate:
                        # Omit every original line containing this symbol, not
                        # only the signature: comments or calls are shortcuts.
                        source = "\n".join(
                            line for line in source.splitlines()
                            if symbol not in line
                        ).strip()
                        if not source:
                            source = "\n".join(
                                line for line in text.splitlines()[:12]
                                if symbol not in line
                            ).strip()[:450]
                        require(symbol not in source, "required declaration survived ablation")
                else:
                    matches = re.search(re.escape(symbol), text)
                    if matches:
                        start = text.rfind("\n", 0, matches.start()) + 1
                        source = text[start: start + 450]
                    else:
                        source = text[:450]
                source = source[:1100]
                require(source.strip(), "zero evidence not silently represented as a source")
                content = f"Source marker: {markers[row['path']]}\nFile: {row['path']}\n" + source
                return dict(marker=markers[row["path"]], path=row["path"],
                            blob_sha=row["blob_sha"], byte_sha256=row["sha256"],
                            text=content, evidence_sha256=digest(content.encode()))

            cases.append(dict(
                id=digest((repo + "\0" + original["blob_sha"] + "\0" + symbol).encode())[:24],
                root=repo, source_cut=SOURCE_CUT, symbol=symbol,
                question=(f"In the frozen {repo} code, which source marker contains "
                          f"the function declaration for `{symbol}`? Answer with the exact "
                          "source marker (F01 etc.) followed by its evidence label."),
                # The ONLY target-bearing context is the mechanically verified
                # original Git declaration line. No independent human oracle.
                conditions={
                    "none": [],
                    "hybrid_k4": [entry(row) for row in selected],
                    "mechanical_support": [entry(original)],
                    "removed_declaration": [entry(original, ablate=True)],
                },
                original_sources=len(docs), original_source_bytes=sum(row["bytes"] for row in docs),
                source_identity_digest=digest(canonical([(x["path"], x["blob_sha"]) for x in docs])),
                prerequisite_is_machine_checked_not_human=True,
            ))
    require(len(cases) == PROBE_COUNT_PER_REPO * len(EVALUATION)
            and len({c["id"] for c in cases}) == len(cases), "ambiguous probe census")
    return dict(
        schema=SCHEMA, source_zip_sha256=SOURCE_SHA, independent_reopen_zip_sha256=REOPEN_SHA,
        source_inventory_sha256=INVENTORY_SHA, source_cut=SOURCE_CUT,
        repository_family_proxies=len(EVALUATION), cases=cases,
        conditions=list(CONDITIONS), reader_tiers=list(TIERS),
        token_limit=1024, max_new_tokens=64,
        tools_allowed=False, labels_in_reader_plan=False,
        mechanical_support_marker_visible_to_execution_harness=True,
        verified_mechanical_original_declarations=True,
        independently_human_certified_sufficient_evidence=False,
        learned_memory_tested=False, production_qualified=False,
    )


def plan_from_archives(source_zip: Path, reopen_zip: Path):
    files, blobs = real_source(source_zip, reopen_zip)
    plan = build_plan(files, blobs)
    require(digest(canonical(plan) + b"\n") == FROZEN_PLAN_SHA256,
            "externally precommitted nine-case plan changed")
    return plan


def locked_plan(path: Path, pinned: str):
    require(HEX64.fullmatch(pinned) and path.is_file() and not path.is_symlink(),
            "missing externally pinned plan")
    data = path.read_bytes()
    require(digest(data) == pinned and len(data) <= 2_000_000,
            "registered public reader plan changed")
    plan = strict_json(data)
    require(plan.get("schema") == SCHEMA and plan.get("conditions") == list(CONDITIONS)
            and plan.get("reader_tiers") == list(TIERS)
            and plan.get("token_limit") == 1024 and plan.get("max_new_tokens") == 64
            and len(plan.get("cases", [])) == 9
            and len({r["id"] for r in plan["cases"]}) == 9
            and plan.get("independently_human_certified_sufficient_evidence") is False
            and plan.get("production_qualified") is False, "reader plan census drift")
    for case in plan["cases"]:
        require(case.get("root") in EVALUATION and set(case.get("conditions", {})) == set(CONDITIONS),
                "changed source family or evidence arms")
        for condition, rows in case["conditions"].items():
            require(len(rows) <= 4 and all(digest(r["text"].encode()) == r["evidence_sha256"] for r in rows),
                    "selected evidence bytes changed")
        require(not case["conditions"]["none"] and len(case["conditions"]["mechanical_support"]) == 1
                and len(case["conditions"]["removed_declaration"]) == 1,
                "missing exact study controls")
    return plan


def reader_execute(plan: dict, tier: str, stage: Path, stage_sha: str, output: Path):
    """Real frozen pretrained generation. Caller stages publisher-pinned weights."""
    from reader_reference import ReferenceReader, MODELS, verify_files
    from evidence_bundle import EvidenceBundle, EvidenceSpan
    from native import Document, Question, digest as hepta_digest
    from reviewed_bundle import strict_read

    require(tier in TIERS and stage.is_dir() and not output.exists(), "reader bounds")
    record = strict_read(stage / "stage.json", stage_sha, 1024 * 1024)
    require(record.get("tier") == tier and
            (record.get("repository"), record.get("revision")) == MODELS[tier],
            "staged real Reader origin differs from frozen tier")
    public = strict_read(stage / "publisher.json", record["publisher_sha256"], 1024 * 1024)
    verify_files(stage / "reader", public["files"])
    reader = ReferenceReader(stage / "reader", expected_inventory=strict_read(
        stage / "inventory.json", record["inventory_sha256"], 1024 * 1024)["inventory_digest"])
    output.mkdir(parents=False, exist_ok=False)
    raw_file = output / "original-generation.jsonl"
    expected = {(c["id"], arm) for c in plan["cases"] for arm in CONDITIONS}
    witnessed = set()
    with raw_file.open("x", encoding="utf-8") as journal:
        for case in plan["cases"]:
            q = Question(case["id"], case["root"], case["id"], case["question"],
                         "2026-10-15T00:00:00Z")
            frontier = hepta_digest((case["root"], case["source_identity_digest"]))
            for condition in CONDITIONS:
                original = {}
                spans = []
                for e in case["conditions"][condition]:
                    content = e["text"]
                    doc = Document(
                        hepta_digest((case["id"], e["marker"], content)),
                        case["root"] + ":" + e["blob_sha"], case["id"],
                        "real-git-blob", SOURCE_CUT, content,
                    )
                    original[doc.identity] = doc
                    spans.append(EvidenceSpan(doc.identity, doc.root, doc.scope,
                                              doc.session, doc.observed_at, 0,
                                              len(content.encode()), content,
                                              hepta_digest(content)))
                bundle = EvidenceBundle(hepta_digest(asdict(q)), frontier,
                                        tuple(spans), condition)
                key = (case["id"], condition)
                require(key not in witnessed, "duplicate real model generation")
                witnessed.add(key)
                row = dict(case_id=case["id"], condition=condition,
                           tier=tier, reader_identity=reader.identity,
                           reader_profile=reader.profile,
                           question_sha256=digest(case["question"].encode()),
                           evidence_sha256=digest(canonical(case["conditions"][condition])),
                           status="failed", answer=None, receipt=None)
                try:
                    answer, receipt = reader.answer(
                        q, bundle, original, frontier=frontier, revoked=set(),
                        token_limit=plan["token_limit"])
                    row.update(status="succeeded", answer=answer, receipt=receipt)
                except Exception as exc:
                    # Failed attempts remain in all denominators; no replacement.
                    row["error"] = type(exc).__name__ + ": " + str(exc)[:512]
                journal.write(json.dumps(row, sort_keys=True, ensure_ascii=False, allow_nan=False) + "\n")
                journal.flush()
                os.fsync(journal.fileno())
    reader.verify_frozen()
    require(witnessed == expected, "incomplete real model attempt census")
    emitted = [strict_json(x) for x in raw_file.read_bytes().splitlines()]
    completed = sum(row["status"] == "succeeded" for row in emitted)
    return dict(tier=tier, cases=len(plan["cases"]), attempts=len(witnessed),
                completed_model_calls=completed, all_calls_successful=completed == len(witnessed),
                output_sha256=digest(raw_file.read_bytes()),
                model_weight_identity=reader.identity, reader_profile=reader.profile,
                actual_model_executions=completed,
                production_qualified=False)


def score_outputs(plan: dict, sources: tuple, journals: dict):
    """Post-generation independent mechanical scoring; never modify answers."""
    files, blobs = sources
    require(canonical(build_plan(files, blobs)) == canonical(plan),
            "source-only plan cannot be regenerated from frozen Git corpus")
    targets = {}
    for case in plan["cases"]:
        root, symbol = case["root"], case["symbol"]
        choices = []
        for row in files:
            if row["repo"] != root or row["partition"] != "evaluation" or not row["path"].endswith((".py", ".rs")):
                continue
            try:
                text = blobs[(root, row["path"])].decode("utf-8")
            except UnicodeDecodeError:
                continue
            if symbol in [name for name, _ in declarations(text)]:
                choices.append(row["path"])
        require(len(choices) == 1, "independent original declaration became ambiguous")
        actual = next((e["marker"] for e in case["conditions"]["mechanical_support"]
                       if e["path"] == choices[0]), None)
        require(actual is not None, "mechanically sufficient source was not delivered")
        targets[case["id"]] = (actual, choices[0])
    results, seen, identities = {}, {}, {}
    for tier in TIERS:
        raw = journals[tier]
        require(isinstance(raw, list), "model-generation journal required")
        matches = set()
        for row in raw:
            require(isinstance(row, dict) and set(("case_id", "tier", "condition", "status", "answer", "receipt")).issubset(row),
                    "missing original model evidence")
            key = (row["case_id"], row["condition"])
            require(row["tier"] == tier and key not in matches
                    and row["case_id"] in targets and row["condition"] in CONDITIONS,
                    "unexpected duplicate original model answer")
            matches.add(key)
            case = next(c for c in plan["cases"] if c["id"] == row["case_id"])
            require(row["question_sha256"] == digest(case["question"].encode())
                    and row["evidence_sha256"] == digest(canonical(case["conditions"][row["condition"]])),
                    "model inference detached from frozen source/question")
            ok = row["status"] == "succeeded"
            require(row["status"] in ("succeeded", "failed") and
                    (not ok or (isinstance(row["answer"], str) and isinstance(row["receipt"], dict))),
                    "original attempt status inconsistent")
            if ok:
                receipt = row["receipt"]
                require(row["reader_identity"] == receipt.get("reader_identity")
                        and row["reader_profile"] == receipt.get("reader_profile")
                        and isinstance(row["reader_identity"], str)
                        and HEX64.fullmatch(row["reader_identity"])
                        and isinstance(row["reader_profile"], str)
                        and HEX64.fullmatch(row["reader_profile"]),
                        "actual Reader receipts differ from declared model identity")
                require(type(receipt.get("input_tokens")) is int and
                        0 < receipt["input_tokens"] <= plan["token_limit"]
                        and type(receipt.get("generated_tokens")) is int and
                        0 < receipt["generated_tokens"] <= plan["max_new_tokens"]
                        and receipt["input_tokens"] + receipt["generated_tokens"] <= 1100
                        and type(receipt.get("seconds")) in (int, float)
                        and 0 <= receipt["seconds"] < 7200
                        and receipt.get("trainable_parameters") == 0
                        and receipt.get("answer_postprocessed") is False
                        and receipt.get("production_accepted") is False,
                        "incompatible generation/budget/frozen Reader receipt")
            parsed = MARKER.fullmatch(row["answer"]) if ok else None
            correct = parsed is not None and parsed[1] == targets[row["case_id"]][0]
            evidence = case["conditions"][row["condition"]]
            cited = (re.findall(r"\[E[1-9][0-9]*\]", row["answer"]) if ok else [])
            cited_ids = {int(x[2:-1]) for x in cited}
            delivery = {i for i, e in enumerate(evidence, 1) if e["path"] == targets[row["case_id"]][1]}
            invalid_labels = len(cited_ids - set(range(1, len(evidence) + 1)))
            complete_cited = correct and bool(delivery) and bool(cited_ids & delivery) and not invalid_labels
            seen.setdefault(tier, []).append(dict(case_id=row["case_id"],
                root=case["root"], condition=row["condition"], succeeded_call=ok,
                strict_correct=correct, necessary_source_delivered=bool(delivery),
                complete_original_citation=complete_cited, invalid_citation_labels=invalid_labels,
                input_tokens=(row["receipt"] or {}).get("input_tokens"),
                output_tokens=(row["receipt"] or {}).get("generated_tokens"),
                inference_seconds=(row["receipt"] or {}).get("seconds")))
        require(matches == {(c["id"], a) for c in plan["cases"] for a in CONDITIONS},
                "missing original model answers")
        identities[tier] = {
            (r["reader_identity"], r["reader_profile"])
            for r in raw if r["status"] == "succeeded"
        }
        require(len(identities[tier]) == 1, "mixed or missing frozen model identities")
        results[tier] = {}
        for arm in CONDITIONS:
            rows = [r for r in seen[tier] if r["condition"] == arm]
            results[tier][arm] = dict(
                attempts=len(rows), successful_model_calls=sum(r["succeeded_call"] for r in rows),
                strict_correct=sum(r["strict_correct"] for r in rows),
                original_correct_and_cited=sum(r["complete_original_citation"] for r in rows),
                invalid_citation_labels=sum(r["invalid_citation_labels"] for r in rows),
                required_source_delivered=sum(r["necessary_source_delivered"] for r in rows),
                input_tokens=sum(r["input_tokens"] or 0 for r in rows),
                generated_tokens=sum(r["output_tokens"] or 0 for r in rows),
                inference_seconds=sum(r["inference_seconds"] or 0 for r in rows),
            )
    require(next(iter(identities[TIERS[0]]))[0] != next(iter(identities[TIERS[1]]))[0],
            "stronger reference reader must be distinct from small reader")
    for tier in TIERS:
        for condition in CONDITIONS:
            rows = {r["case_id"]: r for r in seen[tier] if r["condition"] == condition}
            require(len(rows) == len(plan["cases"]), "incomplete paired score cohort")
    return dict(
        schema="hepta.memory.real-git-reader-mechanical-score.v1",
        source_outer_zip_sha256=SOURCE_SHA,
        source_independent_reopen_sha256=REOPEN_SHA,
        input_repository_family_proxies=len(EVALUATION),
        original_question_count=len(plan["cases"]),
        original_real_model_calls=sum(v["successful_model_calls"] for r in results.values() for v in r.values()),
        reader_conditions=results,
        original_model_inventory_and_profile_claims={
            tier: dict(reader_identity=next(iter(identities[tier]))[0],
                       reader_profile=next(iter(identities[tier]))[1])
            for tier in TIERS
        },
        exact_identifier_mechanical_task=True,
        original_mechanical_support_marker_derivable_from_public_source=True,
        independently_authenticated_model_calls=False,
        independent_human_sufficiency_review=False,
        learned_memory_gain_established=False,
        prompt_and_reader_profiles_differ_across_tiers=True,
        future_source_population=False,
        complete_lifecycle_tco=None,
        missing_lifecycle_costs=["deployed maintenance", "revocation", "recovery", "raw source retention allocation"],
        production_qualified=False,
    )


def write_once(path: Path, data: bytes):
    require(not path.exists() and not path.is_symlink(), "output must not exist")
    with path.open("xb") as file:
        file.write(data)
        file.flush()
        os.fsync(file.fileno())


def cli():
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest="command", required=True)
    stage = sub.add_parser("prepare")
    stage.add_argument("--source-zip", type=Path, required=True)
    stage.add_argument("--reopen-zip", type=Path, required=True)
    stage.add_argument("--plan", type=Path, required=True)
    native = sub.add_parser("run")
    native.add_argument("--plan", type=Path, required=True)
    native.add_argument("--plan-sha256", required=True)
    native.add_argument("--model", type=Path, required=True)
    native.add_argument("--stage-sha256", required=True)
    native.add_argument("--tier", choices=TIERS, required=True)
    native.add_argument("--output", type=Path, required=True)
    score = sub.add_parser("score")
    score.add_argument("--source-zip", type=Path, required=True)
    score.add_argument("--reopen-zip", type=Path, required=True)
    score.add_argument("--plan", type=Path, required=True)
    score.add_argument("--plan-sha256", required=True)
    for tier in TIERS:
        score.add_argument("--" + tier, type=Path, required=True)
    score.add_argument("--output", type=Path, required=True)
    args = p.parse_args()
    if args.command == "prepare":
        plan = plan_from_archives(args.source_zip, args.reopen_zip)
        write_once(args.plan, canonical(plan) + b"\n")
        print(json.dumps(dict(cases=len(plan["cases"]), source_sha256=SOURCE_SHA,
                              public_plan_sha256=digest(args.plan.read_bytes()),
                              independent_semantic_review=False), sort_keys=True))
    if args.command == "run":
        plan = locked_plan(args.plan, args.plan_sha256)
        require(args.plan_sha256 == FROZEN_PLAN_SHA256,
                "source-derived preregistered plan SHA differs")
        result = reader_execute(plan, args.tier, args.model, args.stage_sha256, args.output)
        write_once(args.output / "generation-report.json", canonical(result) + b"\n")
        print(json.dumps(result, sort_keys=True))
    if args.command == "score":
        plan = locked_plan(args.plan, args.plan_sha256)
        require(args.plan_sha256 == FROZEN_PLAN_SHA256,
                "source-derived preregistered plan SHA differs")
        sources = real_source(args.source_zip, args.reopen_zip)
        journals = {}
        for tier in TIERS:
            f = getattr(args, tier.replace("-", "_"))
            require(f.is_file() and not f.is_symlink() and f.stat().st_size < 8_000_000,
                    "bounded original generation journal required")
            journals[tier] = [strict_json(line) for line in f.read_bytes().splitlines()]
        report = score_outputs(plan, sources, journals)
        write_once(args.output, canonical(report) + b"\n")
        print(json.dumps(dict(verified_original_model_calls=report["original_real_model_calls"],
                              independent_human_review=False, production_qualified=False), sort_keys=True))


if __name__ == "__main__":
    cli()
