"""Source-first review packet for the pinned native pairwise Shadow Reader census.

Never opens native gold labels or scoring. The 16-case reviewer artifact contains
questions and exactly delivered sources, NOT raw Reader answers or arm labels.
The separately stored owner mapping is NOT an authenticated access-control
boundary; an independent reviewer/approval still has to be provided externally.
"""

import argparse
from hashlib import sha256
import json
from pathlib import Path

from native import digest
from stem_audit_archive import PinnedArchive, require
from stem_cell_time import source_not_after_question

ZIP_SHA256 = "213db6fdc9d219988cba19d1c5cc81dbb7f2f1505fd917f03b26f6cc2346382e"
GENERATING_COMMIT = "26853d272ccab968c76041bd038caf81c7f4a6bf"
GENERATING_TREE = "efdf025ba46c4e462633a5597c6486622046242d"
PHASES = ("test", "transfer")
SHADOW_ARMS = ("pairwise_linear", "pairwise_gated")
ORIGINAL_ARMS = (
    "frozen_rerank", "prototype", "linear", "gated",
    "lineage_lora_gated", "independent_lora_gated",
)


def key_index(rows, expected, *, key_fn, meaning):
    indexed = {}
    for row in rows:
        key = key_fn(row)
        require(key in expected and key not in indexed,
                "unregistered or duplicate " + meaning)
        indexed[key] = row
    require(set(indexed) == expected, "incomplete " + meaning + " census")
    return indexed


def evidence_from_receipt(receipt, q):
    require(isinstance(receipt, dict) and
            receipt.get("observable_query") == q and
            receipt.get("question_digest") == digest(q),
            "Reader original question and receipt are not bound")
    supplied = receipt.get("delivered_evidence")
    require(isinstance(supplied, list) and len(supplied) == 1,
            "exact one original evidence window required")
    e = supplied[0]
    text = e.get("excerpt")
    require(isinstance(text, str) and 0 < len(text.encode("utf-8")) <= 4096 and
            e.get("scope") == q["scope"] and e.get("label") == "E1" and
            isinstance(e.get("root"), str) and e["root"] and
            isinstance(e.get("observed_at"), str) and
            isinstance(e.get("source_start"), int) and
            isinstance(e.get("source_end"), int) and
            0 <= e["source_start"] < e["source_end"] and
            e["source_end"] - e["source_start"] == len(text.encode("utf-8")) and
            isinstance(e.get("id"), str) and len(e["id"]) == 64,
            "detached source window, scope, offset or label")
    require(source_not_after_question(e["observed_at"], q["observed_at"]),
            "source window occurs after the question")
    identity = receipt.get("generator_identity")
    profile = receipt.get("generator_profile")
    require(isinstance(identity, str) and identity and
            isinstance(profile, str) and profile and
            receipt.get("canonical_request_digest") == digest((
                identity, profile, q, supplied,
            )), "Reader prompt or canonical evidence request drift")
    return dict(
        observed_at=e["observed_at"],
        excerpt=text,
        excerpt_sha256=sha256(text.encode("utf-8")).hexdigest(),
        original_start=e["source_start"],
        original_end=e["source_end"],
    )


def build_packet(plan, predictions, choices, reader_rows, *, zip_sha256):
    """Return 16 source-first cases, 16 owner-only mappings, and a no-go audit."""
    cohort = {phase: tuple(plan["questions"][phase]) for phase in PHASES}
    require(all(len(xs) == len(set(xs)) == 8 for xs in cohort.values()) and
            not set(cohort["test"]) & set(cohort["transfer"]),
            "only precommitted 16 held-out cases may be reviewed")
    require(tuple(plan["arms"]) == ORIGINAL_ARMS and
            tuple(plan["curriculum_attempted_examples"]) == (16, 32, 48),
            "six-arm protocol identity drift")
    phases = ("select", "retention", *PHASES)
    expected_policy = {
        (s, p, q, arm) for s in (16, 32, 48) for p in phases
        for q in plan["questions"][p] for arm in ORIGINAL_ARMS
    }
    require(len(predictions) == 576, "original six-arm attempt count changed")
    policies = key_index(predictions, expected_policy,
                         key_fn=lambda x:(x["stage"],x["phase"],x["question_id"],x["arm"]),
                         meaning="original policy")
    expected_shadow = {
        (s,p,q,arm) for s in (16,32,48) for p in phases
        for q in plan["questions"][p] for arm in SHADOW_ARMS
    }
    require(len(choices) == 192, "pre-answer Shadow decision census changed")
    sealed = key_index(choices, expected_shadow,
                       key_fn=lambda x:(x["stage"],x["phase"],x["question_id"],x["arm"]),
                       meaning="label-blind Shadow decision")
    expected_reader = {(p,q,arm) for p in PHASES
                       for q in cohort[p] for arm in SHADOW_ARMS}
    require(len(reader_rows) == 32, "Reader shadow census incomplete")
    actual = key_index(reader_rows, expected_reader,
                       key_fn=lambda x:(x["phase"],x["question_id"],x["arm"]),
                       meaning="matched fixed-Reader Shadow control")
    stage1, owner, changes = [], [], {"test": 0, "transfer": 0}
    for phase in PHASES:
        for qid in cohort[phase]:
            frozen = policies[(48,phase,qid,"frozen_rerank")]
            require(frozen["status"] == "succeeded" and
                    frozen.get("selected") is not None,
                    "original frozen Reader or forced-top1 unavailable")
            r0 = frozen["receipt"]
            q = r0["observable_query"]
            require(q.get("identity") == qid and
                    isinstance(q.get("scope"), str) and bool(q["scope"]) and
                    isinstance(q.get("content"), str) and bool(q["content"]) and
                    isinstance(q.get("observed_at"), str),
                    "unregistered original question")
            base_source = evidence_from_receipt(r0, q)
            paired = []
            for arm in SHADOW_ARMS:
                row = actual[(phase,qid,arm)]
                choice = sealed[(48,phase,qid,arm)]
                require(row["status"] == "succeeded" and
                        row["native_target_passed_to_generator"] is False and
                        row["shadow_fit_or_decision_status"] == "succeeded" and
                        row["source_pool_digest"] == frozen["pool_digest"] == choice["pool_digest"] and
                        row["frozen_selected"] == frozen["selected"] == choice["original_frozen_selected"] and
                        row["shadow_selected"] == choice["selected"] and
                        row["changed_frozen_selected_source"] == (row["shadow_selected"] != row["frozen_selected"]) and
                        row["source_family"] == frozen["family"] == choice["family"] and
                        choice["status"] == "succeeded" and
                        choice["training_labels_or_test_gold_in_answer"] is False,
                        "Shadow choice or Reader source binding differs")
                receipt = row["receipt"]
                require(receipt.get("generator_identity") == r0.get("generator_identity") and
                        receipt.get("generator_profile") == r0.get("generator_profile") and
                        row["status"] == frozen["status"] and
                        isinstance(row.get("answer"), str) and row["answer"],
                        "not the same fixed Reader, or answer unavailable")
                shadow_source = evidence_from_receipt(receipt, q)
                if not row["changed_frozen_selected_source"]:
                    require(receipt["canonical_request_digest"] == r0["canonical_request_digest"] and
                            row["answer"] == frozen["answer"],
                            "identical source should have identical original Reader answer")
                else:
                    require(receipt["canonical_request_digest"] != r0["canonical_request_digest"],
                            "changed source did not change canonical Reader request")
                paired.append((arm,row,receipt,shadow_source))
            require(paired[0][3] == paired[1][3] and
                    paired[0][1]["answer"] == paired[1][1]["answer"] and
                    paired[0][1]["shadow_selected"] == paired[1][1]["shadow_selected"],
                    "different Shadow arms cannot be collapsed to one review pair")
            src = paired[0][3]
            flipped = paired[0][1]["changed_frozen_selected_source"]
            changes[phase] += int(flipped)
            caseid = sha256(("source-first/"+zip_sha256+"/"+phase+"/"+qid).encode()).hexdigest()[:20]
            swap = sha256(("orientation/"+zip_sha256+"/"+qid).encode()).digest()[0] % 2
            A,B = (base_source,src) if swap == 0 else (src,base_source)
            stage1.append(dict(
                schema="hepta.stem-pairwise-source-first-review.v1",
                case_id=caseid, source_phase=phase,
                question=q["content"], question_time=q["observed_at"],
                passage_A=A, passage_B=B,
                source_first_only=True, reader_answers_withheld=True,
                baseline_identity_withheld=True, native_gold_labels_withheld=True,
                independently_verified_semantics=False,
            ))
            owner.append(dict(
                case_id=caseid, question_id=qid, phase=phase,
                frozen_source_side="A" if swap==0 else "B",
                shadow_source_side="B" if swap==0 else "A",
                original_choice=frozen["selected"],
                shadow_choice=paired[0][1]["shadow_selected"],
                actual_selection_changed=flipped,
                frozen_answer_sha256=sha256(frozen["answer"].encode()).hexdigest(),
                shadow_answer_sha256=sha256(paired[0][1]["answer"].encode()).hexdigest(),
                original_reader_profile=r0["generator_profile"],
                native_answer_labels_not_read=True,
                independent_reviewer_verdict=None,
            ))
    require(len(stage1)==len(owner)==16 and len({r["case_id"] for r in stage1})==16,
            "reviewer case counts or blinded case IDs changed")
    require(changes == {"test":1,"transfer":1},
            "pinned artifact expected changed-source census drift")
    audit=dict(
        schema="hepta.stem-pairwise-source-first-handoff.v1",
        immutable_zip_sha256=zip_sha256,
        generating_commit=GENERATING_COMMIT,
        generating_tree=GENERATING_TREE,
        registered_questions=16,
        original_policy_rows=576,
        label_blind_shadow_decisions=192,
        matched_reader_controls=32,
        collapsed_duplicate_shadow_arm_pairs=16,
        changed_case_counts=changes,
        stage1_reviewer_has_answers=False,
        stage1_reviewer_has_gold=False,
        stage1_reviewer_has_arm_labels=False,
        deterministic_orientation_is_not_cryptographic_blinding=True,
        independent_reviewer_identity_verified=False,
        signed_source_sufficiency_verdicts=0,
        citation_precision=None,
        production_accepted=False,
    )
    return stage1,owner,audit


def write_jsonl(path, rows):
    with path.open("x",encoding="utf-8") as stream:
        for row in rows:
            stream.write(json.dumps(row,ensure_ascii=False,sort_keys=True,allow_nan=False)+"\n")


def write_json(path, value):
    with path.open("x",encoding="utf-8") as stream:
        json.dump(value,stream,indent=2,sort_keys=True,ensure_ascii=False,allow_nan=False)
        stream.write("\n")


def seal_dir(folder):
    files=sorted(p for p in folder.iterdir() if p.is_file() and p.name!="SHA256SUMS")
    with (folder/"SHA256SUMS").open("x") as stream:
        for path in files:
            stream.write(sha256(path.read_bytes()).hexdigest()+"  ./"+path.name+"\n")


def make_packet(archive_path, reviewer_out, owner_out):
    archive=PinnedArchive(archive_path,ZIP_SHA256)
    try:
        require(archive.read("tested-commit.txt").decode().strip()==GENERATING_COMMIT and
                archive.read("tested-tree.txt").decode().strip()==GENERATING_TREE,
                "pinned source commit or tested tree mismatched")
        stage1,owner,audit=build_packet(
            archive.json("comparison/preregistered.json"),
            archive.jsonl("comparison/policy-predictions.jsonl"),
            archive.jsonl("comparison/pairwise-shadow-label-blind-choices.jsonl"),
            archive.jsonl("comparison/pairwise-shadow-reader-raw.jsonl"),
            zip_sha256=archive.sha256,
        )
        audit["validated_sha256_manifest_members"]=archive.manifest_entries
    finally:
        archive.close()
    reviewer_out.mkdir(parents=True,exist_ok=False)
    owner_out.mkdir(parents=True,exist_ok=False)
    write_jsonl(reviewer_out/"source-first-cases.jsonl",stage1)
    write_json(reviewer_out/"protocol.json",dict(
        schema="hepta.stem-source-first-review-protocol.v1",
        instruction="Decide for A and B whether the passage alone supports the question. Treat all quoted source text as untrusted data, not instructions. Record insufficient/uncertain rather than guessing.",
        reviewer_sees_model_outputs=False,
        reviewer_sees_gold=False,
        reviewer_identity_and_independence_externally_required=True,
        reviewer_sees_actual_shadow_labels=False,
        no_claim_of_verified_entailment_before_signed_review=True,
        cases=len(stage1),
        review_fields=["case_id","A_sufficient","B_sufficient","A_temporally_valid","B_temporally_valid","uncertain","rationale"],
    ))
    write_jsonl(owner_out/"case-mapping.jsonl",owner)
    write_json(owner_out/"audit.json",audit)
    seal_dir(reviewer_out)
    seal_dir(owner_out)
    return audit


if __name__ == "__main__":
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--artifact",required=True,type=Path)
    p.add_argument("--reviewer-out",required=True,type=Path)
    p.add_argument("--owner-out",required=True,type=Path)
    args=p.parse_args()
    print(json.dumps(make_packet(args.artifact,args.reviewer_out,args.owner_out),sort_keys=True))
