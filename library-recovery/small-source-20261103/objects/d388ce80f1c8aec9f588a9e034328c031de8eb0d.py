"""Independent local reproduction of the exact two writer functions fetched from PR #3359.
No claims about the full Hepta source tree or CI.
"""
import json, os, tempfile
from pathlib import Path

class CohortContractError(ValueError):
    pass

def validate_output_destination(output, input_paths, *, protected_image_dir=None):
    try:
        if output.is_symlink():
            raise CohortContractError("output path must not be a symlink")
        if output.exists():
            if not output.is_file() or output.stat().st_nlink != 1:
                raise CohortContractError("output path must be an unlinked regular file")
        resolved_output = output.resolve(strict=False)
        if protected_image_dir is not None:
            protected_root = Path(protected_image_dir).resolve(strict=False)
            if resolved_output.is_relative_to(protected_root):
                raise CohortContractError("receipt output overlaps frozen candidate image directory")
        for source in input_paths:
            if resolved_output == source.resolve(strict=False) or (
                output.exists() and source.exists() and output.samefile(source)
            ):
                raise CohortContractError("output path aliases frozen input evidence")
    except (OSError, RuntimeError) as error:
        raise CohortContractError("cannot verify safe output path") from error

def write_receipt_atomically(dest, result, input_paths, *, protected_image_dir=None):
    validate_output_destination(dest, input_paths, protected_image_dir=protected_image_dir)
    dest.parent.mkdir(parents=True, exist_ok=True)
    validate_output_destination(dest, input_paths, protected_image_dir=protected_image_dir)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
                mode="w", encoding="utf-8", dir=dest.parent,
                prefix=".hepta-ndu-firewall-", suffix=".tmp", delete=False) as handle:
            temporary = Path(handle.name)
            handle.write(json.dumps(result, sort_keys=True, indent=2) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        validate_output_destination(dest, input_paths, protected_image_dir=protected_image_dir)
        os.replace(temporary, dest)
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()

def exercise():
    with tempfile.TemporaryDirectory() as td:
        root=Path(td); frozen=root/'images'; frozen.mkdir(); source=root/'candidate.json'; source.write_bytes(b'original')
        invalid=frozen/'unexpected-created-subdir'/'receipt.json'
        try:
            write_receipt_atomically(invalid,{'status':'fail'},[source],protected_image_dir=frozen)
        except CohortContractError as exc:
            assert 'overlaps frozen' in str(exc), str(exc)
        else: raise AssertionError('Did not fail closed')
        assert not invalid.parent.exists(), 'BUG: writer modified original image directory before rejecting receipt!'
        if hasattr(os,'symlink'):
            alias=root/'alias'; alias.symlink_to(frozen,target_is_directory=True)
            invalid_alias=alias/'another-created-subdir'/'receipt.json'
            try: write_receipt_atomically(invalid_alias,{'status':'fail'},[source],protected_image_dir=frozen)
            except CohortContractError: pass
            else: raise AssertionError('alias was accepted')
            assert not (frozen/'another-created-subdir').exists(), 'BUG: symlink alias changed image directory'
        valid=root/'receipts'/'nested'/'receipt.json'
        write_receipt_atomically(valid,{'status':'fail'},[source],protected_image_dir=frozen)
        assert json.loads(valid.read_text())=={'status':'fail'}
        assert source.read_bytes()==b'original'
    print('PASS: protected paths unchanged and normal nested receipt published')

if __name__=='__main__': exercise()
