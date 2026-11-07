"""Conservative source grouping and deterministic untouched study allocation."""

from collections import defaultdict
from difflib import SequenceMatcher
import hashlib
import re
import unicodedata

SPLIT_SALT = "hepta-sroie-source-allocation-20261107-v1"


def normalized(value):
    value = unicodedata.normalize("NFKC", str(value)).upper()
    return re.sub(r"[^A-Z0-9]", "", value)


def merchant(value):
    value = re.sub(r"\([^)]*\)", " ", unicodedata.normalize("NFKC", str(value)).upper())
    tokens = re.findall(r"[A-Z0-9]+", value)
    return " ".join(word for word in tokens if word not in
                    {"SDN", "BHD", "BERHAD", "LTD", "LIMITED", "ENTERPRISE"})


def connect_sources(records):
    parents = list(range(len(records)))
    edges = []

    def find(index):
        while parents[index] != index:
            parents[index] = parents[parents[index]]
            index = parents[index]
        return index

    def join(left, right, reason):
        a, b = find(left), find(right)
        if a != b:
            parents[max(a, b)] = min(a, b)
            edges.append({"left": records[left]["key"], "right": records[right]["key"],
                          "reason": reason})

    names = [merchant(row["entities"]["company"]) for row in records]
    brands = [" ".join(name.split()[:2]) if name else "UNKNOWN" for name in names]
    addresses = [normalized(row["entities"]["address"]) for row in records]
    for i, row in enumerate(records):
        for j in range(i):
            other = records[j]
            reason = None
            if names[i] == names[j] or brands[i] == brands[j]:
                reason = "merchant_identity"
            elif len(addresses[i]) > 12 and addresses[i] == addresses[j]:
                reason = "same_store_address"
            elif (min(len(names[i]), len(names[j])) >= 6
                  and SequenceMatcher(None, names[i], names[j]).ratio() >= 0.88):
                reason = "merchant_name_variant"
            elif (row["image_sha256"] == other["image_sha256"]
                  or row["pixel_sha256"] == other["pixel_sha256"]):
                reason = "exact_image_or_pixels"
            elif row["transcript_sha256"] == other["transcript_sha256"]:
                reason = "identical_document_transcript"
            elif ((row["dhash"] ^ other["dhash"]).bit_count() <= 4
                  and abs(row["aspect"] / other["aspect"] - 1) <= 0.05):
                a, b = row["word_tokens"], other["word_tokens"]
                if len(a & b) / max(1, len(a | b)) >= 0.75:
                    reason = "near_duplicate_image_and_transcript"
            if reason:
                join(i, j, reason)
    members = defaultdict(list)
    for index, row in enumerate(records):
        members[find(index)].append(row)
    groups = []
    for rows in members.values():
        keys = sorted(row["key"] for row in rows)
        identity = hashlib.sha256(("\n".join(keys)).encode()).hexdigest()[:24]
        disclosed = any("BOOKTAK" in normalized(row["entities"]["company"])
                        or "ABCHOTRADING" in normalized(row["entities"]["company"]) for row in rows)
        groups.append({"source_group": "merchant-" + identity, "members": rows,
                       "previously_disclosed": disclosed})
    return sorted(groups, key=lambda group: group["source_group"]), edges


def allocate(groups):
    eligible = [group for group in groups if any(row["eligible"] for row in group["members"])]
    forced_train = [group for group in eligible if group["previously_disclosed"]]
    free = [group for group in eligible if not group["previously_disclosed"]]
    free.sort(key=lambda group: hashlib.sha256(
        (SPLIT_SALT + group["source_group"]).encode()).hexdigest())
    count = len(eligible)
    dev_count, confirmation_count = max(21, count // 5), max(21, count // 4)
    retention_count = max(21, count // 10)
    needed = dev_count + confirmation_count + 2 * retention_count
    if len(free) < needed or count - needed < 21:
        raise ValueError("Insufficient actual independent source groups for train/dev/confirmation "
                         "and separate 21-group retention validation/test cohorts")
    result = {}
    offset = 0
    for role, n in (("development", dev_count), ("confirmation", confirmation_count),
                    ("retention_validation", retention_count), ("retention_test", retention_count)):
        for group in free[offset:offset + n]:
            result[group["source_group"]] = role
        offset += n
    for group in free[offset:] + forced_train:
        result[group["source_group"]] = "train"
    for group in groups:
        result.setdefault(group["source_group"], "train")
    return result
