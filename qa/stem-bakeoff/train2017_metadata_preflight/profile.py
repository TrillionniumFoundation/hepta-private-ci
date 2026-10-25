"""Candidate source profile, NOT a prospective registration or cohort freeze."""

ARCHIVE_BYTES = 252_907_541
ARCHIVE_SHA256 = "113a836d90195ee1f884e704da6304dfaaecff1f023f49b6ca93c4aaae470268"
P39_BYTES = 372_470
P39_SHA256 = "bdcd27245d5435820ddd6ef305b42bdeca236e4411839f1d209d314547567b23"
MEMBERS = {
    "instances_train2017": (
        469_785_474,
        152_757_829,
        "610fce4944abdeb15354cc765333805529359d12d88f2f711393ca586901d01d",
        500 * 1024**2,
    ),
    "captions_train2017": (
        91_865_115,
        18_816_055,
        "4b62086319480e0739ef390d04084515defb9c213ff13605a036061e33314317",
        100 * 1024**2,
    ),
    "instances_val2017": (
        19_987_840,
        6_529_031,
        "e8c7f7908f1d7278341fae127d0da654f102f11bd7b21d8aeefa635b8c810b6f",
        48 * 1024**2,
    ),
}
TARGETS = {17: "cat", 18: "dog", 19: "horse", 21: "cow"}
LICENSES = {
    4: {
        "id": 4,
        "name": "Attribution License",
        "url": "http://creativecommons.org/licenses/by/2.0/",
    },
    5: {
        "id": 5,
        "name": "Attribution-ShareAlike License",
        "url": "http://creativecommons.org/licenses/by-sa/2.0/",
    },
}
PILOT_SPLITS = {
    "train": {"cat": 16, "dog": 16},
    "dev": {"cat": 8, "dog": 8},
    "calibration": {"cat": 8, "dog": 8},
    "test": {"cat": 16, "dog": 16},
    "ood": {"horse": 8, "cow": 8},
}
REQUIRED = {"cat": 48, "dog": 48, "horse": 8, "cow": 8}
LIMITS = {
    "image_records": 130_000,
    "instance_annotations": 1_000_000,
    "caption_annotations": 650_000,
    "parser_buffer_chars": 4 * 1024**2,
    "address_space_bytes": 4 * 1024**3,
    "receipt_bytes": 16 * 1024**2,
    "new_task_output_bytes": 128 * 1024**2,
    "new_download_bytes": 0,
}
FUTURE_PHOTO_GATES = {
    "max_image_bytes": 2 * 1024**2,
    "total_photo_download_bytes": 140 * 1024**2,
    "max_decoded_pixels": 4_194_304,
    "minimum_dhash_distance": 5,
    "raw_and_rgb_hash_disjointness": "REQUIRED_NOT_RUN",
    "per_photo_attribution_and_rights": "REQUIRED_NOT_RUN",
    "independent_source_seal_publication": "REQUIRED_NOT_RUN",
    "acquisition_enabled": False,
}
