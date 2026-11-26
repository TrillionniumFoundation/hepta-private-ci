"""Certificate renewal must retain the original CA, key, name and lifetime bounds."""

from datetime import datetime, timedelta, timezone
import importlib.machinery
import importlib.util
import ipaddress
import json
from pathlib import Path
import unittest

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

PATH = Path(__file__).with_name("hepta-renew-openbao-leaf")
SPEC = importlib.util.spec_from_loader(
    "bao_leaf_renewal",
    importlib.machinery.SourceFileLoader("bao_leaf_renewal", str(PATH)),
)
renewal = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(renewal)


class LeafRenewalTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.now = datetime.now(timezone.utc).replace(microsecond=0)
        cls.ca_key = rsa.generate_private_key(public_exponent=65537, key_size=3072)
        cls.leaf_key = rsa.generate_private_key(public_exponent=65537, key_size=3072)
        cls.name = x509.Name(
            [x509.NameAttribute(NameOID.COMMON_NAME, "isolated-renewal-CA")]
        )

    def ca(self, lifetime):
        return (
            x509.CertificateBuilder()
            .subject_name(self.name)
            .issuer_name(self.name)
            .public_key(self.ca_key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(self.now - timedelta(days=1))
            .not_valid_after(self.now + lifetime)
            .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
            .sign(self.ca_key, hashes.SHA256())
        )

    def leaf(self, ca, lifetime=timedelta(days=3), *, names=None):
        sans = (
            names
            if names is not None
            else [
                x509.IPAddress(ipaddress.ip_address("127.0.0.1")),
                x509.DNSName("localhost"),
            ]
        )
        return (
            x509.CertificateBuilder()
            .subject_name(
                x509.Name(
                    [
                        x509.NameAttribute(
                            NameOID.COMMON_NAME, "isolated-renewal-listener"
                        )
                    ]
                )
            )
            .issuer_name(ca.subject)
            .public_key(self.leaf_key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(self.now - timedelta(hours=1))
            .not_valid_after(self.now + lifetime)
            .add_extension(
                x509.BasicConstraints(ca=False, path_length=None), critical=True
            )
            .add_extension(
                x509.KeyUsage(
                    True, False, True, False, False, False, False, None, None
                ),
                critical=True,
            )
            .add_extension(
                x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]), critical=False
            )
            .add_extension(x509.SubjectAlternativeName(sans), critical=False)
            .sign(self.ca_key, hashes.SHA256())
        )

    @staticmethod
    def pem(certificate):
        return certificate.public_bytes(serialization.Encoding.PEM)

    @staticmethod
    def key_bytes(key):
        return key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )

    def issue(self, ca, leaf, *, key=None):
        return x509.load_pem_x509_certificate(
            renewal.renewed_certificate(
                self.pem(ca),
                self.key_bytes(self.ca_key),
                self.pem(leaf),
                self.key_bytes(self.leaf_key if key is None else key),
                self.now,
                90,
            )
        )

    def test_real_signature_renews_leaf_without_changing_ca_key_or_names(self):
        ca = self.ca(timedelta(days=100))
        old = self.leaf(ca)
        renewed = self.issue(ca, old)
        renewed.verify_directly_issued_by(ca)
        self.assertEqual(renewed.subject, old.subject)
        self.assertEqual(renewed.issuer, old.issuer)
        self.assertEqual(list(renewed.extensions), list(old.extensions))
        self.assertEqual(
            renewed.public_key().public_numbers(), old.public_key().public_numbers()
        )
        self.assertNotEqual(renewed.serial_number, old.serial_number)
        self.assertEqual(
            renewal.utc_time(renewed, "not_valid_after"), self.now + timedelta(days=90)
        )

    def test_original_ca_expiry_clips_new_leaf_and_near_expiry_rejects(self):
        ca = self.ca(timedelta(days=5))
        renewed = self.issue(ca, self.leaf(ca))
        self.assertEqual(
            renewal.utc_time(renewed, "not_valid_after"),
            renewal.utc_time(ca, "not_valid_after") - timedelta(hours=1),
        )
        expiring = self.ca(timedelta(hours=2))
        with self.assertRaises(ValueError):
            self.issue(expiring, self.leaf(expiring, timedelta(hours=1)))

    def test_different_leaf_key_ca_as_leaf_and_nonlocal_names_cannot_renew(self):
        ca = self.ca(timedelta(days=100))
        with self.assertRaises(ValueError):
            self.issue(ca, self.leaf(ca), key=self.ca_key)
        with self.assertRaises(ValueError):
            self.issue(ca, ca)
        with self.assertRaises(ValueError):
            self.issue(ca, self.leaf(ca, names=[x509.DNSName("example.invalid")]))

    def test_ambiguous_operator_policy_is_rejected(self):
        with self.assertRaises(ValueError):
            json.loads(
                '{"ca_sha256":"one","ca_sha256":"two"}',
                object_pairs_hook=renewal.unique_object,
            )


if __name__ == "__main__":
    unittest.main()
