"""Independent byte and source verifier; does not import experiment scorers."""

import gzip
import hashlib
import json
from pathlib import Path
import re
import struct

import numpy as np
from PIL import Image
import torch


def byte_hash(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read_outputs(delivery):
    paths = {key: Path(value) for key, value in delivery["paths"].items()}
    if any(path.is_symlink() for path in paths.values()):
        raise ValueError("Symlink output is not an immutable delivered file")
    actual_hashes = {key: byte_hash(path) for key, path in paths.items()}
    if actual_hashes != delivery["sha256"]:
        raise ValueError("Actual output bytes differ from their delivery receipt")
    with Image.open(paths["image"]) as image:
        if (image.format, image.mode, image.size) != ("PNG", "L", (56, 28)):
            raise ValueError("Delivered image is outside the declared codec profile")
        pixels = np.asarray(image).copy().astype(np.float32)[None, None] / 255
    caption = paths["text"].read_bytes().decode("utf-8")
    if caption != delivery["caption"]:
        raise ValueError("Actual UTF-8 differs from the claimed caption")
    return pixels, caption


def independent_score(observer, delivery, target_pixels, target_labels):
    pixels, caption = read_outputs(delivery)
    parsed = re.fullmatch(r"left ([0-9]) right ([0-9]) relation (less|equal|greater)", caption.strip())
    digits = [int(parsed[1]), int(parsed[2])] if parsed else None
    with torch.inference_mode():
        value = torch.from_numpy(pixels)
        predicted = [int(observer(value[:, :, :, :28]).argmax(1)[0]),
                     int(observer(value[:, :, :, 28:]).argmax(1)[0])]
    expected = list(map(int, target_labels))
    relation = "less" if expected[0] < expected[1] else "greater" if expected[0] > expected[1] else "equal"
    text_error = np.mean([a != b for a, b in zip(digits, expected)]) if digits else 1.0
    relation_error = float(parsed[3] != relation) if parsed else 1.0
    image_error = np.mean([a != b for a, b in zip(predicted, expected)])
    disagreement = np.mean([a != b for a, b in zip(digits, predicted)]) if digits else 1.0
    mse = float(np.mean((pixels - target_pixels) ** 2))
    utility = 1 - 2 * (.3 * text_error + .15 * relation_error + .35 * image_error + .1 * disagreement + .1 * mse)
    strict = int(text_error == relation_error == image_error == 0)
    preferred_relation_matches = parsed is not None and parsed[3] == ("less" if int(parsed[1]) < int(parsed[2])
        else "greater" if int(parsed[1]) > int(parsed[2]) else "equal")
    feedback = 0
    if preferred_relation_matches:
        feedback = 1 if digits == expected else -1 if digits == expected[::-1] else 0
    return {"utility": float(utility), "strict_success": strict, "feedback": feedback,
        "text_fact": float(text_error), "relation": relation_error, "image_fact": float(image_error),
        "crossmodal_disagreement": float(disagreement), "pixel_mse": mse,
        "image_digits": predicted, "caption_digits": digits}


def verify_sources(directory, assets):
    metadata = json.loads((directory / "SOURCES.json").read_text())
    public = torch.load(directory / "PUBLIC.pt", weights_only=True)
    private = torch.load(directory / "PRIVATE.pt", weights_only=True)
    origins = {}
    pins = {row["path"]: row["sha256"] for row in json.loads((assets / "RESTORATION.json").read_text())["selected_files"]}
    for origin, image_name, label_name in (
            ("train", "train-images-idx3-ubyte.gz", "train-labels-idx1-ubyte.gz"),
            ("test", "t10k-images-idx3-ubyte.gz", "t10k-labels-idx1-ubyte.gz")):
        for name in (image_name, label_name):
            if byte_hash(assets / "ndu-data" / name) != pins["ndu-data/" + name]:
                raise ValueError("Official image or label gzip differs from the immutable restoration receipt")
        raw = gzip.decompress((assets / "ndu-data" / image_name).read_bytes())
        compressed_labels = (assets / "ndu-data" / label_name).read_bytes()
        expected_md5 = "d53e105ee54ea40749a09fcbcd1e9432" if origin == "train" else "ec29112dd5afa0611ce80d1b7f02629c"
        if hashlib.md5(compressed_labels).hexdigest() != expected_md5:
            raise ValueError("Published official label MD5 differs")
        label_raw = gzip.decompress(compressed_labels)
        magic, count, height, width = struct.unpack(">IIII", raw[:16])
        if (magic, height, width) != (2051, 28, 28) or len(raw) != 16 + count * 784:
            raise ValueError("Official image record is malformed")
        if struct.unpack(">II", label_raw[:8]) != (2049, count) or len(label_raw) != 8 + count:
            raise ValueError("Official image/label counts disagree")
        origins[origin] = (np.frombuffer(raw[16:], np.uint8).reshape(count, 1, 28, 28), list(label_raw[8:]))
    seen = set()
    for index, record in enumerate(metadata):
        pixels, labels = [], []
        for identity in record["source_ids"]:
            prefix, origin, position, expected_digest = identity.split(":")
            if prefix != "mnist" or identity in seen:
                raise ValueError("Repeated or invalid source identity")
            seen.add(identity)
            source_pixels, source_labels = origins[origin]
            value = source_pixels[int(position)]
            if hashlib.sha256(value.tobytes()).hexdigest() != expected_digest:
                raise ValueError("Source bytes do not match their identity")
            pixels.append(value)
            labels.append(source_labels[int(position)])
        if private["preferences"][index]:
            pixels, labels = pixels[::-1], labels[::-1]
        expected = np.concatenate(pixels, axis=2).astype(np.float32) / 255
        if not np.array_equal(private["pixels"][index].numpy(), expected):
            raise ValueError("Private target is not the preferred original source order")
        if private["labels"][index].tolist() != labels:
            raise ValueError("Private target labels differ from official labels")
        if int(public["tokens"][index, 1]) != 9:
            raise ValueError("Hidden preferred order entered initial public instruction")
        if torch.any(public["pixels"][index][public["mask"][index] == 0] != 0):
            raise ValueError("Missing source pixels entered the public masked input")
    return metadata, public, private
