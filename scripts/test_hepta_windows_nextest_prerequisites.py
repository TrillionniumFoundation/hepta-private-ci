"""Source guards for Windows archive fixtures and NTFS test prerequisites.

These checks reject workflow regressions. They do not execute PowerShell,
Windows, an archived binary, or the original native filesystem experiment.
"""

from pathlib import Path
import re
import unittest


ROOT = Path(__file__).resolve().parents[1]
FULL = ROOT / ".github/workflows/rust-ci-full.yml"
PLATFORM = ROOT / ".github/workflows/rust-ci-full-nextest-platform.yml"
PREFLIGHT = "Verify Windows fixture location and NTFS test temporary directory"


def block(text: str, marker: str, indent: int) -> str:
    match = re.search(r"^" + " " * indent + re.escape(marker) + r"\n", text, re.M)
    if match is None:
        raise AssertionError(f"missing block: {marker}")
    following = re.search(r"^ {" + str(indent) + r"}\S", text[match.end() :], re.M)
    end = match.end() + following.start() if following else len(text)
    return text[match.start() : end]


def check_contract(full: str, platform: str) -> None:
    arm = block(full, "tests_windows_arm64:", 2)
    assert "      runner: windows-11-arm\n" in arm
    assert not re.search(r"^      archive_runner(?:_group|_labels)?:", arm, re.M)
    assert "      target: aarch64-pc-windows-msvc\n" in arm
    archive = block(platform, "archive:", 2)
    shard = block(platform, "shard:", 2)
    for job in (archive, shard):
        assert "        working-directory: codex-rs\n" in job
        assert not re.search(r"^    continue-on-error:", job, re.M)
    assert (
        "windows_workspace_root: ${{ steps.windows_workspace.outputs.root }}" in archive
    )
    capture = block(archive, "- name: Record compiled Windows workspace location", 6)
    assert "        id: windows_workspace\n" in capture
    assert archive.index("Record compiled Windows workspace location") < archive.index(
        "      - name: Build nextest archive\n"
    )
    preflight = block(shard, "- name: " + PREFLIGHT, 6)
    for step in (capture, preflight):
        assert "        if: ${{ runner.os == 'Windows' }}\n" in step
        assert "        shell: pwsh\n" in step
        assert "$ErrorActionPreference = 'Stop'" in step
        assert "(Resolve-Path -LiteralPath . -ErrorAction Stop).ProviderPath" in step
        assert not re.search(
            r"continue-on-error|SilentlyContinue|\bcatch\b|exit 0", step
        )
    assert '"root=$root" | Out-File -FilePath $env:GITHUB_OUTPUT' in capture
    assert (
        "ARCHIVE_WINDOWS_WORKSPACE_ROOT: ${{ needs.archive.outputs.windows_workspace_root }}"
        in preflight
    )
    assert shard.index("- uses: ./.github/actions/setup-ci") < shard.index(PREFLIGHT)
    assert shard.index(PREFLIGHT) < shard.index("      - name: tests\n")
    required = [
        "if ([string]::IsNullOrWhiteSpace($env:ARCHIVE_WINDOWS_WORKSPACE_ROOT) -or\n"
        "              -not [string]::Equals($root, $env:ARCHIVE_WINDOWS_WORKSPACE_ROOT, [StringComparison]::OrdinalIgnoreCase)) {\n"
        '            throw "Archived Windows fixtures require the producer workspace:',
        "$testTemp = Join-Path $env:RUNNER_TEMP (\"ntfs-\" + [guid]::NewGuid().ToString('N'))",
        "New-Item -ItemType Directory -Path $testTemp -ErrorAction Stop",
        "$probe = Join-Path $testTemp 'volume.preflight'",
        "[System.IO.File]::WriteAllText($probe, 'nextest temporary volume preflight')",
        "$volumes = @(Get-Volume -FilePath $probe -ErrorAction Stop)",
        "if ($volumes.Count -ne 1 -or $volumes[0].FileSystem -ne 'NTFS') {\n"
        '            throw "Windows tests require an observed NTFS temporary volume at $probe"',
        "Remove-Item -LiteralPath $probe -ErrorAction Stop",
        '"TEMP=$testTemp" | Out-File -FilePath $env:GITHUB_ENV',
        '"TMP=$testTemp" | Out-File -FilePath $env:GITHUB_ENV',
    ]
    positions = [preflight.index(text) for text in required]
    assert positions == sorted(positions)
    assert "      fail-fast: false\n" in shard
    assert "        shard: [1, 2, 3, 4]\n" in shard
    for original in (
        "--no-fail-fast",
        '--workspace-remap "${workspace_root}"',
        '--partition "hash:${{ matrix.shard }}/4"',
    ):
        assert original in shard


class WindowsNextestPrerequisiteTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.full = FULL.read_text(encoding="utf-8")
        cls.platform = PLATFORM.read_text(encoding="utf-8")

    def test_current_workflow_contract(self):
        check_contract(self.full, self.platform)

    def test_cross_host_archive_override_is_rejected(self):
        for suffix in ("", "_group", "_labels"):
            with self.subTest(suffix=suffix):
                mutated = self.full.replace(
                    "  tests_windows_arm64:\n",
                    "  tests_windows_arm64:\n      archive_runner"
                    + suffix
                    + ": other\n",
                    1,
                )
                with self.assertRaises(AssertionError):
                    check_contract(mutated, self.platform)

    def test_fixture_path_guard_cannot_be_bypassed(self):
        for old, new in (
            ("-not [string]::Equals($root,", "[string]::Equals($root,"),
            ("[string]::IsNullOrWhiteSpace", "[string]::IsNullOrEmpty"),
            (
                'throw "Archived Windows fixtures',
                'Write-Warning "Archived Windows fixtures',
            ),
            ("${{ needs.archive.outputs.windows_workspace_root }}", "C:\\assumed"),
        ):
            with self.subTest(old=old), self.assertRaises((AssertionError, ValueError)):
                check_contract(self.full, self.platform.replace(old, new, 1))

    def test_volume_is_observed_at_the_created_file_not_an_assumed_drive(self):
        with self.assertRaises(ValueError):
            check_contract(
                self.full,
                self.platform.replace(
                    "Get-Volume -FilePath $probe", "Get-Volume -DriveLetter C", 1
                ),
            )

    def test_non_ntfs_or_unknown_volume_must_fail_closed(self):
        for old, new in (
            ("$volumes.Count -ne 1 -or", "$volumes.Count -eq 1 -and"),
            (".FileSystem -ne 'NTFS'", ".FileSystem -ne 'ReFS'"),
            ('throw "Windows tests require', 'Write-Warning "Windows tests require'),
            ("$ErrorActionPreference = 'Stop'", "$ErrorActionPreference = 'Continue'"),
        ):
            with self.subTest(old=old), self.assertRaises((AssertionError, ValueError)):
                check_contract(self.full, self.platform.replace(old, new))

    def test_preflight_cannot_follow_test_execution(self):
        shard = block(self.platform, "shard:", 2)
        preflight = block(shard, "- name: " + PREFLIGHT, 6)
        mutated = self.platform.replace(preflight, "", 1)
        mutated = mutated.replace(
            "      - name: tests\n", "      - name: tests\n" + preflight, 1
        )
        with self.assertRaises(AssertionError):
            check_contract(self.full, mutated)

    def test_original_partition_and_workspace_remap_remain_required(self):
        for text in (
            '--workspace-remap "${workspace_root}"',
            "--no-fail-fast",
            "shard: [1, 2, 3, 4]",
        ):
            with self.subTest(text=text), self.assertRaises(AssertionError):
                check_contract(self.full, self.platform.replace(text, "removed", 1))


if __name__ == "__main__":
    unittest.main()
