from __future__ import annotations

import tarfile
import tempfile
from pathlib import Path
import unittest
import zipfile

from docs.acceptance import build_candidate


ROOT = Path(__file__).resolve().parents[1]


class AcceptanceCandidateTests(unittest.TestCase):
    def test_agulater_release_archives_match_the_published_layout(self) -> None:
        cases = (
            ("windows-x64", "zip", "agulater.exe"),
            ("linux-x64", "tar.gz", "agulater"),
            ("macos-x64", "tar.gz", "agulater"),
            ("macos-arm64", "tar.gz", "agulater"),
        )
        for platform_name, archive_format, executable in cases:
            with self.subTest(platform=platform_name), tempfile.TemporaryDirectory(
                prefix="agentkube-candidate-test-"
            ) as temporary:
                temporary_root = Path(temporary)
                repository = temporary_root / "agulater"
                repository.mkdir()
                binary = temporary_root / "fixture-binary"
                binary.write_bytes(b"standalone")
                (repository / "LICENSE").write_bytes(b"project-license")
                (repository / "THIRD_PARTY_NOTICES").write_bytes(b"notices")

                archive = build_candidate.package_agulater_release(
                    binary=binary,
                    platform_name=platform_name,
                    version="v9.8.7",
                    archive_format=archive_format,
                    output=temporary_root / "dist",
                    repository_root=repository,
                )

                bundle = f"agulater-v9.8.7-{platform_name}"
                expected = {
                    f"{bundle}/{executable}": b"standalone",
                    f"{bundle}/LICENSE": b"project-license",
                    f"{bundle}/THIRD_PARTY_NOTICES": b"notices",
                }
                if archive_format == "zip":
                    with zipfile.ZipFile(archive) as packaged:
                        actual = {
                            name: packaged.read(name)
                            for name in packaged.namelist()
                            if not name.endswith("/")
                        }
                else:
                    with tarfile.open(archive, "r:gz") as packaged:
                        actual = {
                            member.name: packaged.extractfile(member).read()
                            for member in packaged.getmembers()
                            if member.isfile()
                        }
                self.assertEqual(actual, expected)

    def test_owner_checklist_consumes_archive_and_checks_notices(self) -> None:
        checklist = (ROOT / "docs" / "acceptance" / "README.md").read_text(
            encoding="utf-8"
        )

        self.assertIn("`THIRD_PARTY_NOTICES.md`", checklist)
        self.assertIn("`Cargo.lock`", checklist)
        self.assertIn("$Candidate.artifacts.agulater_release.path", checklist)
        self.assertIn("AGULATER_ACCEPTANCE_ARCHIVE", checklist)
        self.assertIn('Resolve-Path "agulater/scripts/install.ps1"', checklist)
        self.assertIn('Resolve-Path "agulater/scripts/install.sh"', checklist)


if __name__ == "__main__":
    unittest.main()
