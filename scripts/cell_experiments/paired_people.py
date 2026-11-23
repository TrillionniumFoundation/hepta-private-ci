"""Check private enrollment originals for a paired study when the original site has them."""

import hashlib
import json
import os

from . import data
from .paired_intake import digest_field, owner_file, require, sha, witness


def check_training_statement(owner, completion):
    failure, correction = (
        digest_field(completion[k]) for k in ("failure_sha256", "correction_sha256")
    )
    text = (
        f"Hepta paired learning consent v1\nStudy SHA-256: {completion['study_sha256']}\n"
        "I authorize Hepta to train the study candidate using only these records.\n"
        f"Failure SHA-256: {failure}\nCorrection SHA-256: {correction}"
    )
    require(
        owner["consent_text_sha256"] == sha(text.encode()),
        "A's exact allowed training records differ",
    )


def check(config, arrival, native, request_sha, candidate, training_run):
    """The site's enrolled-person reference must identify a person across their accounts."""
    left = witness(config, "training-person")
    right = witness(config, "person-" + arrival["arrival_id"])
    require(
        left["schema"] == "hepta.paired-intake.training-person.v1"
        and right["schema"] == "hepta.paired-intake.evaluation-person.v1",
        "original A/B enrollment records required",
    )
    for item in (left, right):
        for field in (
            "authority_sha256",
            "enrollment_receipt_sha256",
            "person_sha256",
            "study_principal_sha256",
            "consent_delivery_id",
        ):
            digest_field(item[field])
        original = item["enrollment_receipt_sha256"]
        with owner_file(config, "enrollment-" + original + ".bin") as stream:
            require(
                os.fstat(stream.fileno()).st_size > 0
                and hashlib.file_digest(stream, "sha256").hexdigest() == original,
                "original enrollment material differs from the issuing site receipt",
            )
    require(
        left["authority_sha256"] == right["authority_sha256"]
        and left["person_sha256"] != right["person_sha256"]
        and left["study_principal_sha256"] != right["study_principal_sha256"]
        and left["enrollment_receipt_sha256"] != right["enrollment_receipt_sha256"],
        "distinct original people from one enrolled-person authority required",
    )
    require(
        left["sequence"] < arrival["sequence"] <= right["sequence"],
        "training enrollment must precede the task and evaluation enrollment must cover it",
    )
    completion = json.loads((training_run / "COMPLETED.json").read_bytes())
    owner = json.loads((training_run / "OWNER.json").read_bytes())
    require(
        completion["schema"] == "hepta.paired-learning.source-completion.v1"
        and completion["scope"] == config["scope"]
        and completion["study_sha256"] == config["study"]
        and completion["freeze_sha256"] == config["freeze"]
        and completion["candidate_sha256"] == candidate
        and digest_field(left["source_completion_sha256"]) == data.digest(completion),
        "site enrollment does not cover this frozen training completion",
    )
    require(
        digest_field(completion["owner_receipt_sha256"]) == data.digest(owner)
        and owner["schema"] == "hepta.paired-learning.consent-readback.v1"
        and owner["use"] == "train"
        and owner["study_sha256"] == config["study"]
        and owner["study_principal_sha256"] == left["study_principal_sha256"]
        and owner["delivery_id"] == left["consent_delivery_id"],
        "A original training authorization differs from the enrolled principal",
    )
    check_training_statement(owner, completion)
    require(
        right["arrival_id"] == arrival["arrival_id"]
        and right["record_sha256"] == arrival["record_sha256"]
        and right["request_sha256"] == request_sha
        and right["consent_delivery_id"] == native["delivery_id"]
        and right["study_principal_sha256"] == native["study_principal_sha256"],
        "B original enrollment differs from the received task and live consent",
    )
    return dict(
        authority_sha256=left["authority_sha256"],
        a_enrollment_sha256=data.digest(left),
        b_enrollment_sha256=data.digest(right),
        source_completion_sha256=data.digest(completion),
        training_owner_sha256=data.digest(owner),
    )
