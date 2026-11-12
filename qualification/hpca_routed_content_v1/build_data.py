"""Build one frozen operator-authored development panel, before model execution."""

from hashlib import sha256
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def main():
    tasks, train, evaluation = [], {}, {}
    for split in ("train", "content"):
        for pair in range(32):
            for group in range(2):
                answer = (pair // (group + 1)) % 2 == 0
                suffix = sha256(f"{split}/{group}/{pair}".encode()).hexdigest()[:8]
                suffix = "".join("abcdefghjklmnpqr"[int(c, 16)] for c in suffix)
                obj = ("Lumo" if split == "train" else "Neri") + suffix
                value = (
                    ("red" if answer else "blue")
                    if group == 0
                    else ("circle" if answer else "square")
                )
                feature, wanted = (
                    ("color", "red") if group == 0 else ("shape", "circle")
                )
                if split == "train":
                    question = (
                        f"Record: {obj} has {feature} {value}. "
                        f"Does {obj} have {feature} {wanted}?"
                    )
                elif pair % 2:
                    question = (
                        f"The {feature} assigned to {obj} is {value}. "
                        f"Is the statement '{obj} has {feature} {wanted}' true?"
                    )
                else:
                    question = (
                        f"Read this fact: {obj}'s {feature} is {value}. "
                        f"According to the fact, does {obj} have {feature} {wanted}?"
                    )
                row = {
                    "id": f"{split}-{group}-{pair:02}",
                    "split": split,
                    "group": group,
                    "pair": pair,
                    "source_cluster": obj,
                    "question": question,
                }
                tasks.append(row)
                (train if split == "train" else evaluation)[row["id"]] = (
                    "yes" if answer else "no"
                )
    original_path = (
        ROOT.parent / "hpca-neuroscience-20261110/PROSPECTIVE_DEVEL_DATA.json"
    )
    original = json.loads(original_path.read_bytes())
    retention = [t for t in original["tasks"] if t["split"] == "retention"]
    for i, task in enumerate(retention):
        row = {k: task[k] for k in ("id", "split", "source_cluster", "question")}
        row["group"] = (
            i // 2
        ) % 2  # Fixed per fact cluster, never a function of truth.
        row["pair"] = i // 2
        tasks.append(row)
        evaluation[row["id"]] = task["truth"]
    for name, value in (
        ("TASKS.json", {"tasks": tasks}),
        ("TRAIN_FEEDBACK.json", train),
        ("EVAL_LABELS.json", evaluation),
    ):
        (ROOT / name).write_text(
            (
                '{"tasks": [\n'
                + ",\n".join(json.dumps(t, sort_keys=True) for t in value["tasks"])
                + "\n]}\n"
            )
            if name == "TASKS.json"
            else json.dumps(value, sort_keys=True, indent=2) + "\n"
        )
    print(
        json.dumps(
            {
                "retention_origin_sha256": sha256(
                    original_path.read_bytes()
                ).hexdigest(),
                "files": {
                    n: sha256((ROOT / n).read_bytes()).hexdigest()
                    for n in ("TASKS.json", "TRAIN_FEEDBACK.json", "EVAL_LABELS.json")
                },
            },
            sort_keys=True,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
