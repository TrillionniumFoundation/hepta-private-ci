"""Explicit lossless-decoder arms, separate from pure parameter inference."""

from dataclasses import dataclass
from pathlib import Path
import time

import numpy as np

from .codec import decode_exact, decode_factor, encode_factor, exact_matrix_archives
from .semantic_router import canonical, digest


@dataclass(frozen=True)
class DecodedReader:
    """A charged, exact decoded numeric cache; this is not a parameter-only cell."""

    years: tuple[int, ...]
    matrix: np.ndarray
    mask: np.ndarray
    archive_sha256: str

    def read(self, coordinates):
        rows = {year: index for index, year in enumerate(self.years)}
        output = []
        for year, month in coordinates:
            if type(year) is not int or type(month) is not int:
                raise ValueError("calendar addresses must be integers")
            if (
                year not in rows
                or not 1 <= month <= 12
                or not self.mask[rows[year], month - 1]
            ):
                output.append(None)
            else:
                output.append(int(self.matrix[rows[year], month - 1]))
        return output


def write_codec_memories(source, parameter_reader, directory):
    path = Path(directory)
    path.mkdir(parents=True, exist_ok=False)
    values = np.asarray(source["values"], dtype=np.int32)
    residual, residual_receipt = encode_factor(
        parameter_reader.bank, values, model_storage="external", method="best"
    )
    (path / "residual.archive").write_bytes(residual)
    started = time.perf_counter()
    decoded, mask = decode_factor(
        (path / "residual.archive").read_bytes(),
        model=parameter_reader.bank,
        expected_sha256=residual_receipt["archive_sha256"],
    )
    decode_seconds = time.perf_counter() - started
    if not np.array_equal(decoded, values):
        raise AssertionError("saved lossless residual decoder changed canonical values")
    decoded.setflags(write=False)
    mask.setflags(write=False)
    residual_reader = DecodedReader(
        tuple(source["years"]), decoded, mask, residual_receipt["archive_sha256"]
    )
    metadata = {
        "domain": source["domain"],
        "years": source["years"],
        "scale": source["scale"],
        "unit": source["unit"],
    }
    encoded_addresses = canonical(metadata) + b"\n"
    (path / "addresses.json").write_bytes(encoded_addresses)
    started = time.perf_counter()
    exact_candidates = exact_matrix_archives(values)
    exact_encode_seconds = time.perf_counter() - started
    exact_name, exact_payload = min(
        exact_candidates.items(), key=lambda pair: (len(pair[1]), pair[0])
    )
    exact_hash = digest(exact_payload)
    (path / "strong-exact.archive").write_bytes(exact_payload)
    started = time.perf_counter()
    exact_matrix, exact_mask = decode_exact(
        (path / "strong-exact.archive").read_bytes(), expected_sha256=exact_hash
    )
    exact_decode_seconds = time.perf_counter() - started
    if not np.array_equal(exact_matrix, values):
        raise AssertionError("saved strong exact decoder changed canonical values")
    exact_matrix.setflags(write=False)
    exact_mask.setflags(write=False)
    exact_reader = DecodedReader(
        tuple(source["years"]), exact_matrix, exact_mask, exact_hash
    )
    receipt = {
        "factor_residual": {
            **residual_receipt,
            "save_load_exact": True,
            "decode_seconds": decode_seconds,
            "resident_decoded_cache_bytes": decoded.nbytes + mask.nbytes,
            "address_metadata_bytes": len(encoded_addresses),
            "deployed_bytes": residual_receipt["complete_standalone_bytes"]
            + len(encoded_addresses),
        },
        "strong_exact": {
            "selected_encoding": exact_name,
            "archive_bytes": len(exact_payload),
            "archive_sha256": exact_hash,
            "all_candidate_archive_bytes": {
                key: len(value) for key, value in exact_candidates.items()
            },
            "all_candidate_encode_seconds": exact_encode_seconds,
            "decode_seconds": exact_decode_seconds,
            "save_load_exact": True,
            "resident_decoded_cache_bytes": exact_matrix.nbytes + exact_mask.nbytes,
            "address_metadata_bytes": len(encoded_addresses),
            "deployed_bytes": len(exact_payload) + len(encoded_addresses),
        },
        "both_readers_use_only_saved_archive_decoding": True,
        "both_readers_materialize_exact_values_in_memory": True,
        "parameter_only": False,
    }
    (path / "receipt.json").write_bytes(canonical(receipt) + b"\n")
    return residual_reader, exact_reader, receipt
