import unittest

from observe_pinned_rbe_openssh import IMAGE, validate_image


class PublishedImageBindingTests(unittest.TestCase):
    def test_verified_manifest_and_native_platform_bind_local_config(self):
        image = {
            "RepoDigests": [IMAGE.removeprefix("docker.io/")],
            "Os": "linux",
            "Architecture": "amd64",
            "Id": "sha256:" + "1" * 64,
        }
        self.assertEqual(validate_image(image), image["Id"])
        for change in (
            {"RepoDigests": ["other@sha256:" + "2" * 64]},
            {"Architecture": "arm64"},
            {"Os": "windows"},
            {"Id": "sha256:" + "g" * 64},
        ):
            with self.subTest(change=change), self.assertRaises(ValueError):
                validate_image({**image, **change})
