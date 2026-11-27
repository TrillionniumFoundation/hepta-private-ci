"""Ephemeral certificates and real HTTPS servers for behavior verification."""

from datetime import datetime, timedelta, timezone
import hashlib
import ipaddress
from pathlib import Path
import threading

from cryptography import x509
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

from authority_contract import Membership
from tls_wire import Credentials, server


def membership():
    writer = Ed25519PrivateKey.generate()
    keys = {f"replica-{i}": Ed25519PrivateKey.generate() for i in range(3)}
    members = Membership(
        "memory-authority",
        writer.public_key().public_bytes_raw().hex(),
        {name: key.public_key().public_bytes_raw().hex() for name, key in keys.items()},
    )
    return members, writer, keys


def certificates(root, purposes):
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    now = datetime.now(timezone.utc)
    ca_key = Ed25519PrivateKey.generate()
    subject = x509.Name(
        [x509.NameAttribute(NameOID.COMMON_NAME, "Ephemeral memory behavior test CA")]
    )
    ca = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(subject)
        .public_key(ca_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=1))
        .not_valid_after(now + timedelta(hours=2))
        .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
        .add_extension(
            x509.KeyUsage(
                digital_signature=True,
                content_commitment=False,
                key_encipherment=False,
                data_encipherment=False,
                key_agreement=False,
                key_cert_sign=True,
                crl_sign=True,
                encipher_only=None,
                decipher_only=None,
            ),
            critical=True,
        )
        .sign(ca_key, algorithm=None)
    )
    ca_path = root / "ca.pem"
    ca_path.write_bytes(ca.public_bytes(serialization.Encoding.PEM))
    result = {}
    for name, purpose in purposes.items():
        key = Ed25519PrivateKey.generate()
        leaf_subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, name)])
        usages = (
            [ExtendedKeyUsageOID.SERVER_AUTH]
            if purpose == "server"
            else [ExtendedKeyUsageOID.CLIENT_AUTH]
        )
        builder = (
            x509.CertificateBuilder()
            .subject_name(leaf_subject)
            .issuer_name(subject)
            .public_key(key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(now - timedelta(minutes=1))
            .not_valid_after(now + timedelta(hours=1))
            .add_extension(
                x509.BasicConstraints(ca=False, path_length=None), critical=True
            )
            .add_extension(x509.ExtendedKeyUsage(usages), critical=False)
        )
        if purpose == "server":
            builder = builder.add_extension(
                x509.SubjectAlternativeName(
                    [
                        x509.DNSName("localhost"),
                        x509.IPAddress(ipaddress.ip_address("127.0.0.1")),
                    ]
                ),
                critical=False,
            )
        certificate = builder.sign(ca_key, algorithm=None)
        certificate_path, key_path = root / (name + ".pem"), root / (name + ".key")
        certificate_path.write_bytes(
            certificate.public_bytes(serialization.Encoding.PEM)
        )
        key_path.write_bytes(
            key.private_bytes(
                serialization.Encoding.PEM,
                serialization.PrivateFormat.PKCS8,
                serialization.NoEncryption(),
            )
        )
        key_path.chmod(0o600)
        result[name] = dict(
            credentials=Credentials(str(ca_path), str(certificate_path), str(key_path)),
            certificate_sha256=hashlib.sha256(
                certificate.public_bytes(serialization.Encoding.DER)
            ).hexdigest(),
        )
    return result


class LiveServer:
    def __init__(self, application, credentials, grants):
        self.instance = server(application, credentials, grants, host="127.0.0.1")
        self.address = "https://127.0.0.1:" + str(self.instance.server_port)
        self.thread = threading.Thread(target=self.instance.serve_forever, daemon=True)
        self.thread.start()

    def close(self):
        self.instance.shutdown()
        self.instance.server_close()
        self.thread.join(timeout=5)
        if self.thread.is_alive():
            raise RuntimeError("HTTPS server did not stop")
