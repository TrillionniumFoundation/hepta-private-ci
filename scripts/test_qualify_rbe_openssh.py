import copy
import unittest

from qualify_rbe_openssh import validate_build


class BuildBindingTests(unittest.TestCase):
    def setUp(self):
        self.image_id = "sha256:" + "1" * 64
        self.image = {"Id": self.image_id, "Os": "linux", "Architecture": "amd64"}
        self.base = {
            "uri": "pkg:docker/ubuntu@24.04?platform=linux%2Famd64",
            "digest": {"sha256": "2" * 64},
        }
        self.metadata = {
            "containerimage.config.digest": self.image_id,
            "buildx.build.provenance": {"materials": [self.base]},
        }

    def test_observed_base_and_tested_local_image_stay_distinct_from_registry_digest(
        self,
    ):
        result = validate_build(self.metadata, self.image, self.image_id)
        self.assertEqual(
            result,
            {
                "local_image_id": self.image_id,
                "resolved_base_material": self.base,
                "build_output_digest": None,
                "registry_publication_digest": None,
            },
        )

    def test_missing_or_wrong_platform_material_cannot_establish_base(self):
        for materials in (
            [],
            [self.base, self.base],
            [{**self.base, "uri": "pkg:docker/ubuntu@24.04?platform=linux%2Farm64"}],
            [{**self.base, "digest": {"sha256": "unobserved"}}],
        ):
            with self.subTest(materials=materials), self.assertRaises(ValueError):
                validate_build(
                    {
                        **self.metadata,
                        "buildx.build.provenance": {"materials": materials},
                    },
                    self.image,
                    self.image_id,
                )

    def test_image_substitution_refuses_even_when_build_is_successful(self):
        for changes in (
            {"Id": "sha256:" + "3" * 64},
            {"Architecture": "arm64"},
            {"Os": "windows"},
        ):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                validate_build(self.metadata, {**self.image, **changes}, self.image_id)
        altered = copy.deepcopy(self.metadata)
        altered["containerimage.config.digest"] = "sha256:" + "4" * 64
        with self.assertRaises(ValueError):
            validate_build(altered, self.image, self.image_id)
