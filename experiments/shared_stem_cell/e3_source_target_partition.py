"""Partition source-bound ScienceQA labels without exposing held-out targets.

Research-only pure helper. In predictor mode, TEST labels are neither read from
the label callback nor serialized or hashed. This protects the model-facing
stage, but it does not authenticate the dataset owner or independent observer.
"""
from __future__ import annotations


class TargetPartitionError(ValueError):
    pass


def partition_source_labels(label_lookups, answer, *, include_test_labels: bool):
    """Return TRAIN/CAL labels and optionally TEST labels.

    Critical ordering: the TEST condition is evaluated BEFORE calling `answer`.
    The withheld original value and its content-derived digest are unavailable
    in the label-blind mode; no placeholder labels are synthesized.
    """
    if type(include_test_labels) is not bool or not callable(answer):
        raise TargetPartitionError("explicit target-visibility mode and callback required")
    if type(label_lookups) is not list or not label_lookups:
        raise TargetPartitionError("bounded source membership required")
    fit, held, seen = [], [], set()
    if len(label_lookups) > 256:
        raise TargetPartitionError("too many source rows")
    for row in label_lookups:
        if type(row) is not tuple or len(row) != 4:
            raise TargetPartitionError("invalid source identity tuple")
        rid, group, split, index = row
        if not (type(rid) is str and type(group) is str
                and type(split) is str and split in ("train", "validation", "test")
                and type(index) is int and index >= 0):
            raise TargetPartitionError("invalid partition or source identifier")
        if rid in seen:
            raise TargetPartitionError("duplicate source identifier")
        seen.add(rid)
        if split == "test" and not include_test_labels:
            continue
        value = answer(split, index)
        if type(value) is not int or not 0 <= value < 4:
            raise TargetPartitionError("invalid original answer")
        record = {"id": rid, "group": group, "split": split, "label": value}
        (held if split == "test" else fit).append(record)
    if not fit or (include_test_labels and not held):
        raise TargetPartitionError("missing original training or heldout cohort")
    if not include_test_labels and held:
        raise TargetPartitionError("heldout target entered predictor stage")
    return fit, held
