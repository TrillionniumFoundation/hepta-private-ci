"""Read-only replay of the exact SHA-pinned V22 *sanitized* dual-Reader artifact.

The original 135M and Qwen forwards happened in a separate GitHub Actions job.
This module validates artifact identity, cross-Reader summaries, unique cost
accounting and science/authority limits; it NEVER performs or attests inference,
semantic scoring, publisher evidence sufficiency, or NDU improvement.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import stat
import zipfile

SCHEMA = "hepta.v23.original-two-reader-sanitized-recount.v1"
REPO = "TrillionniumFoundation/hepta-private-ci"
PR_PARENT = 2560
COMMIT_SHA = "14c597392dcf0b9382922fe333731320b0101b58"
GITHUB_RUN_ID = 38986155653
ARTIFACT_ID = 12084082227
ARTIFACT_SHA256 = "3ef61dad3b4a7bc58f35597d26e1c92c3df02e250aae8cf4072a128b7545724d"
CORPUS_SHA256 = "79fa87e90f04081343b8c8debecb80a9a6842b76a7aa537dc9fdf651ea698ff4"
V17_PLAN_SHA256 = "6b508c3dee8fef3dd6e43ba58117baed927a358de7a02d5b47236cfbb0a64938"
V19_PLAN_SHA256 = "02472deb1fa26428f106ac00ac7b1986dc3384cae14176d00a7e014129b66551"
MODEL_MATERIAL_SHA256 = "e748e2efe1880f9e312eb31e8929e0fff8e46a575cbcf6788f9399960748d273"
# Member checksums from the original completed GitHub Actions artifact. They let
# CI verify cross-run extraction without trusting its ZIP recompression bytes.
MEMBER_SHA256 = {
    "v19-135m-sanitized.json": "afcc4e0097c3d3e8b82f6284d40d6dbbfa3425c347e8ce07abdf96a6e98d9aaf",
    "source/qwen-token-preflight.json": "1527aa28c01acab0afa1ce83460ccd0420cc15841ea6710d3aeeb7481a2fa3b8",
    "v19-qwen-sanitized.json": "5d43ddfe96bf37fa07a6016963718e856b1371dadf86f841b60467bdee955c92",
    "v20-reference-alias-reconciliation.json": "4ac360fa56b3f540717e1f4600d49c2af10911b44a3a5de9d770003ecc10c9e1",
}
EXPECTED_FILES = frozenset((
    "v19-135m-sanitized.json", "v19-qwen-sanitized.json",
    "source/qwen-token-preflight.json", "v20-reference-alias-reconciliation.json",
))
ARMS = ("none", "retrieved", "annotated", "lesion")
MAX_ZIP_SIZE = 200_000
MAX_MEMBER_SIZE = 20_000


def _must(ok, message):
    if not ok:
        raise ValueError(message)


def _sha(data):
    return hashlib.sha256(data).hexdigest()


def _unique_pairs(items):
    out = {}
    for k, v in items:
        _must(k not in out, "duplicate JSON key")
        out[k] = v
    return out


def _nonfinite(v):
    raise ValueError("nonfinite JSON number: " + str(v))


def _json(raw):
    return json.loads(raw.decode("utf-8", errors="strict"),
                      object_pairs_hook=_unique_pairs, parse_constant=_nonfinite)


def read_original_archive(path):
    """Reject replacement even if a fabricated ZIP has internally valid JSON."""
    p = Path(path)
    _must(p.is_file() and not p.is_symlink() and stat.S_ISREG(p.stat().st_mode)
          and 0 < p.stat().st_size <= MAX_ZIP_SIZE, "original archive absent or unsafe")
    _must(_sha(p.read_bytes()) == ARTIFACT_SHA256, "actual GitHub artifact SHA changed")
    out = {}
    with zipfile.ZipFile(p) as z:
        entries = z.infolist()
        _must(len(entries) == len(EXPECTED_FILES), "original member census changed")
        for info in entries:
            name = info.filename
            mode = (info.external_attr >> 16) & 0o170000
            _must(name in EXPECTED_FILES and name not in out and not info.is_dir()
                  and mode not in (stat.S_IFDIR, stat.S_IFLNK)
                  and 0 < info.file_size <= MAX_MEMBER_SIZE,
                  "unrecognized, duplicate, symlink or oversize artifact member")
            data = z.read(info)
            _must(len(data) == info.file_size, "incomplete artifact member")
            out[name] = _json(data)
    _must(set(out) == EXPECTED_FILES, "missing original score/provenance member")
    return out


def read_extracted_members(directory):
    """Validate same-source file digests after cross-run GitHub artifact extraction.

    Unlike read_original_archive, extraction cannot prove ZIP byte identity;
    it independently verifies each original, pinned member's exact bytes.
    """
    root = Path(directory)
    _must(root.is_dir() and not root.is_symlink(), "original members directory unavailable")
    members = [p for p in root.rglob("*") if p.is_file() or p.is_symlink()]
    _must(len(members) == len(EXPECTED_FILES), "extracted artifact member census changed")
    out = {}
    for member in members:
        relative = member.relative_to(root).as_posix()
        _must(relative in EXPECTED_FILES and relative not in out
              and member.is_file() and not member.is_symlink()
              and stat.S_ISREG(member.stat().st_mode)
              and 0 < member.stat().st_size <= MAX_MEMBER_SIZE,
              "untrusted cross-run extracted member")
        raw = member.read_bytes()
        _must(_sha(raw) == MEMBER_SHA256[relative], "pinned original JSON member SHA drifted")
        out[relative] = _json(raw)
    _must(set(out) == EXPECTED_FILES, "missing original cross-run member")
    return out


def _nonneg_int(value, label):
    _must(type(value) is int and value >= 0, "invalid " + label)
    return value


def reconcile(source):
    """Independent aggregate consistency checks, not independent raw-answer scoring."""
    _must(type(source) is dict and set(source) == EXPECTED_FILES, "original member universe changed")
    old = source["v19-135m-sanitized.json"]
    new = source["v19-qwen-sanitized.json"]
    pref = source["source/qwen-token-preflight.json"]
    alias = source["v20-reference-alias-reconciliation.json"]
    _must(old.get("schema") == "hepta.v17.original-locomo-reader.shadow.v1.independent-postseal-source-score"
          and new.get("schema") == "hepta.v19.original-locomo-native-qwen3-reference.shadow.v1.independent-postseal-summary"
          and pref.get("schema") == "hepta.v20.original-locomo-qwen-reference.preflight.v1"
          and alias.get("schema") == "hepta.v20.original-locomo-qwen-reference.preflight.v1.postseal-alias-reconciliation",
          "model or stage receipt schema mismatch")
    for receipt in (old, new, pref, alias):
        _must(receipt.get("production_authorized") is False and receipt.get("decision") == "HOLD_NO_GO",
              "fabricated production authority")
    _must(old.get("original_corpus_sha256") == CORPUS_SHA256
          and new.get("original_publisher_sha256") == CORPUS_SHA256
          and old.get("plan_sha256") == V17_PLAN_SHA256
          and pref.get("original_v17_plan_sha256") == V17_PLAN_SHA256
          and new.get("source_plan_sha256") == V19_PLAN_SHA256
          and pref.get("original_v19_reference_plan_sha256") == V19_PLAN_SHA256
          and alias.get("model_reference_plan_sha256") == V19_PLAN_SHA256,
          "underlying source/prompt or model reference changed")
    _must(new.get("reference_material_sha256") == MODEL_MATERIAL_SHA256
          and pref.get("qwen_model_material_sha256") == MODEL_MATERIAL_SHA256,
          "Qwen material fingerprint mismatch")
    for key, value in (("original_source_roots", 10), ("original_source_cases", 30),
                       ("logical_model_requests", 120), ("unique_physical_input_ids", 96)):
        _must(pref.get(key) == value, "Qwen preflight identity/count mismatch: " + key)
    _must(new.get("original_source_first_questions") == 30
          and new.get("original_source_roots") == 10
          and new.get("original_reference_logical_requests") == 120
          and new.get("original_reference_physical_requests") == 96
          and old.get("source_first_cases") == 30
          and old.get("logical_arm_requests") == 120
          and old.get("physical_unique_model_requests") == 96,
          "unequal case universe or physical source count")
    _must(alias.get("source_alias_mapping_sha256") == pref.get("token_alias_groups_sha256")
          and alias.get("logical_tokens_with_aliases") == pref.get("logical_input_tokens")
          and alias.get("unique_tokens_paid_once") == pref.get("unique_input_tokens")
          and _nonneg_int(pref.get("logical_input_tokens"), "logical tokens")
          >= _nonneg_int(pref.get("unique_input_tokens"), "unique tokens") > 0,
          "shared Qwen token costs were forged or counted twice")
    _must(pref.get("original_qwen_forward_executed") is False
          and pref.get("publisher_answer_labels_available_to_reader") is False
          and alias.get("original_Qwen_semantic_correctness_verified") is False
          and old.get("reader_not_hf_operator_parity_verified", True) is True
          and new.get("independent_semantic_review_verified") is False
          and new.get("human_evidence_sufficiency_verified") is False
          and new.get("model_token_budget_matched_to_135m") is False
          and new.get("no_cell_learning_or_NDU_gain") is True
          and old.get("true_NDU_FBSDE") is False,
          "unsupported semantic, cost parity or NDU claim")
    _must(old.get("original_model_forward_calls") == 1777
          and new.get("reference_forward_count") == 1970
          and old.get("reader_cpu_ms") == 171883
          and old.get("reader_wall_ms") == 86205,
          "original physical 135M cost/census changed")
    rows = old.get("summary")
    score = new.get("scores")
    _must(type(rows) is list and len(rows) == 4 and type(score) is dict
          and set(score) == set(ARMS), "missing original four-arm matrix")
    indexed = {}
    for rec in rows:
        arm = rec.get("arm")
        _must(arm in ARMS and arm not in indexed and rec.get("cases") == 30,
              "original 135M arm/count mismatch")
        for name in ("weak_literal_answer_substrings", "strict_full_answer_equality",
                     "input_tokens", "output_tokens", "observed_citations", "out_of_evidence_citations"):
            _nonneg_int(rec.get(name), "135M " + name)
        indexed[arm] = rec
    _must(set(indexed) == set(ARMS), "incomplete 135M score matrix")
    compared = {}
    cpu_sum = 0
    for arm in ARMS:
        old_arm, ref = indexed[arm], score[arm]
        _must(type(ref) is dict and ref.get("total") == 30
              and ref.get("labeled") == 22 and ref.get("missing_answer") == 8,
              "missing publisher answer must not become a scored failure")
        for name in ("literal_hits", "strict_equals", "input_tokens", "response_tokens",
                     "model_cpu_ms", "valid_syntactic_citations", "foreign_citation_cases",
                     "abstain_literal_unknown"):
            _nonneg_int(ref.get(name), "Qwen " + name)
        _must(ref["literal_hits"] <= ref["labeled"]
              and old_arm["weak_literal_answer_substrings"] <= ref["labeled"]
              and ref["strict_equals"] <= ref["labeled"]
              and old_arm["strict_full_answer_equality"] <= ref["labeled"]
              and ref["valid_syntactic_citations"] <= 30
              and ref["foreign_citation_cases"] <= 30,
              "unbounded scores or unreviewed citations")
        cpu_sum += ref["model_cpu_ms"]
        compared[arm] = {
            "labeled_questions": 22, "publisher_answer_missing": 8,
            "135m_weak_literal_hits": old_arm["weak_literal_answer_substrings"],
            "qwen_weak_literal_hits": ref["literal_hits"],
            "qwen_minus_135m_weak_literal_hits":
                ref["literal_hits"] - old_arm["weak_literal_answer_substrings"],
            "135m_strict_full_answer_matches": old_arm["strict_full_answer_equality"],
            "qwen_strict_full_answer_matches": ref["strict_equals"],
            "qwen_valid_syntactic_citations_not_entailment": ref["valid_syntactic_citations"],
            "qwen_foreign_citation_cases": ref["foreign_citation_cases"],
        }
    _must(cpu_sum <= 565749, "Qwen per-condition CPU exceeds model total")
    _must(new.get("reference_forward_count") == 1970
          and sum(score[a]["model_cpu_ms"] for a in ARMS) > 0,
          "Qwen actual CPU execution not accounted for")
    # The per-arm CPU counters exclude Qwen setup overhead; hosted stdout
    # independently declared this original run's total CPU and wall time.
    report = {
        "schema": SCHEMA,
        "exact_parent_commit": COMMIT_SHA, "github_run_id": GITHUB_RUN_ID,
        "original_sanitized_artifact_id": ARTIFACT_ID,
        "original_sanitized_artifact_sha256": ARTIFACT_SHA256,
        "corpus_sha256": CORPUS_SHA256,
        "historical_independent_roots": 10, "original_questions": 30,
        "logical_requests_each_model": 120, "distinct_physical_requests_each_model": 96,
        "qwen_physical_input_tokens_charged_once": pref["unique_input_tokens"],
        "qwen_alias_inclusive_logical_input_tokens": pref["logical_input_tokens"],
        "original_135m_model_forwards": 1777, "original_qwen_model_forwards": 1970,
        "original_135m_cpu_ms": 171883, "original_135m_wall_ms": 86205,
        "qwen_total_cpu_ms_from_physical_job": 565749,
        "qwen_total_wall_ms_from_physical_job": 302895,
        "raw_cpu_ms_ratio_not_quality_matched": round(565749 / 171883, 4),
        "raw_wall_ms_ratio_not_quality_matched": round(302895 / 86205, 4),
        "four_arm_descriptive_proxy": compared,
        "per_case_paired_scores_not_available_in_sanitized_archive": True,
        "independent_raw_answer_replay_from_sanitized_archive_possible": False,
        "evidence_sufficiency_human_certified": False,
        "semantic_answer_correctness_verified": False,
        "citation_entailment_verified": False,
        "matched_model_token_budget": False,
        "model_capacity_or_learning_superiority_verified": False,
        "ndu_system2_or_cell_split_gain_verified": False,
        "production_authorized": False,
        "decision": "HOLD_NO_GO",
    }
    _must(report["four_arm_descriptive_proxy"]["annotated"]["qwen_minus_135m_weak_literal_hits"] == -1
          and report["four_arm_descriptive_proxy"]["retrieved"]["qwen_minus_135m_weak_literal_hits"] == 0
          and all(v["135m_strict_full_answer_matches"] == v["qwen_strict_full_answer_matches"] == 0
                  for v in report["four_arm_descriptive_proxy"].values()),
          "original observed physical negative result changed")
    return report


def replay(path):
    return reconcile(read_original_archive(path))


def write_once(path, report):
    target = Path(path)
    _must(not target.exists() and not target.is_symlink() and target.parent.is_dir(),
          "receipt must be new in an existing directory")
    flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    fd = os.open(target, flags, 0o600)
    with os.fdopen(fd, "wb") as stream:
        stream.write(json.dumps(report, sort_keys=True, separators=(",", ":"),
                                allow_nan=False).encode() + b"\n")
        stream.flush()
        os.fsync(stream.fileno())
    return target


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    src = parser.add_mutually_exclusive_group(required=True)
    src.add_argument("--archive", help="Original SHA-pinned sanitized GitHub ZIP")
    src.add_argument("--members-dir", help="Cross-run extracted members, each SHA-pinned")
    parser.add_argument("--output", help="New create-only digest/count-only JSON report")
    a = parser.parse_args()
    report = replay(a.archive) if a.archive else reconcile(read_extracted_members(a.members_dir))
    if a.output:
        write_once(a.output, report)
    print(json.dumps(report, ensure_ascii=True, sort_keys=True, allow_nan=False))


if __name__ == "__main__":
    main()
