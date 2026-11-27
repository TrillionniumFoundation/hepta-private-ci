import argparse
import gzip
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import tarfile


def checked(raw, expected_size, expected_hash):
    if len(raw) != expected_size or hashlib.sha256(raw).hexdigest() != expected_hash:
        raise ValueError('Evidence identity mismatch')
    return raw


def main():
    parser = argparse.ArgumentParser(description='Verify and restore the complete Round 03 evidence archive.')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    here = Path(__file__).resolve().parent
    manifest = json.loads((here / 'evidence-manifest.json').read_text())
    compressed = b''.join(
        checked((here / entry['path']).read_bytes(), entry['bytes'], entry['sha256'])
        for entry in manifest['parts']
    )
    checked(compressed, manifest['gzip_bytes'], manifest['gzip_sha256'])
    raw_tar = checked(gzip.decompress(compressed), manifest['tar_bytes'], manifest['tar_sha256'])
    if args.output.exists():
        raise ValueError('Output must be a new directory')
    with tarfile.open(fileobj=io.BytesIO(raw_tar), mode='r:') as archive:
        expected_names = [entry['path'] for entry in manifest['files']]
        if archive.getnames() != expected_names:
            raise ValueError('Archive membership mismatch')
        verified = []
        for entry in manifest['files']:
            name = PurePosixPath(entry['path'])
            member = archive.getmember(entry['path'])
            if name.is_absolute() or '..' in name.parts or not member.isfile():
                raise ValueError('Invalid archive path or member')
            contents = checked(archive.extractfile(member).read(), entry['bytes'], entry['sha256'])
            verified.append((name, contents, entry['mode']))
    args.output.mkdir(parents=True)
    for name, contents, mode in verified:
        destination = args.output.joinpath(*name.parts)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(contents)
        destination.chmod(mode & 0o777)
    print(f"Verified and restored {len(verified)} files for source {manifest['source_commit']}")


if __name__ == '__main__':
    main()
