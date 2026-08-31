#!/usr/bin/env python3
"""Build a host-local three-repository acceptance bundle without publishing it."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import tarfile
import tempfile
import tomllib
import zipfile


ROOT = Path(__file__).resolve().parents[2]
AGUL = ROOT / "agul"
AGULATER = ROOT / "agulater"


def host_release() -> tuple[str, str, str, str, str]:
    system = platform.system()
    machine = platform.machine().lower()
    if system == "Windows" and machine in {"amd64", "x86_64"}:
        return (
            "windows-x64",
            "x86_64-pc-windows-msvc",
            "zip",
            "agul.exe",
            "bun-windows-x64",
        )
    if system == "Linux" and machine in {"amd64", "x86_64"}:
        return (
            "linux-x64",
            "x86_64-unknown-linux-gnu",
            "tar.gz",
            "agul",
            "bun-linux-x64",
        )
    if system == "Darwin" and machine in {"amd64", "x86_64"}:
        return (
            "macos-x64",
            "x86_64-apple-darwin",
            "tar.gz",
            "agul",
            "bun-darwin-x64",
        )
    if system == "Darwin" and machine in {"arm64", "aarch64"}:
        return (
            "macos-arm64",
            "aarch64-apple-darwin",
            "tar.gz",
            "agul",
            "bun-darwin-arm64",
        )
    raise SystemExit(f"unsupported acceptance host: {system} {platform.machine()}")


def run(*command: str, cwd: Path = ROOT) -> None:
    subprocess.run(command, cwd=cwd, check=True)


def git_state(repository: Path) -> dict[str, object]:
    commit = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repository,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    dirty = bool(
        subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=repository,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
    )
    return {"commit": commit, "dirty": dirty}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def package_agulater_release(
    *,
    binary: Path,
    platform_name: str,
    version: str,
    archive_format: str,
    output: Path,
    repository_root: Path = AGULATER,
) -> Path:
    binary = binary.resolve(strict=True)
    version = version.removeprefix("v")
    bundle_name = f"agulater-v{version}-{platform_name}"
    executable = "agulater.exe" if platform_name == "windows-x64" else "agulater"
    suffix = ".zip" if archive_format == "zip" else ".tar.gz"
    destination = output / f"{bundle_name}{suffix}"

    output.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="agulater-release-") as temporary:
        bundle = Path(temporary) / bundle_name
        bundle.mkdir()
        packaged_binary = bundle / executable
        shutil.copy2(binary, packaged_binary)
        if executable == "agulater":
            packaged_binary.chmod(packaged_binary.stat().st_mode | 0o111)
        for name in ("LICENSE", "THIRD_PARTY_NOTICES"):
            shutil.copy2(repository_root / name, bundle / name)

        if archive_format == "zip":
            with zipfile.ZipFile(destination, "w", zipfile.ZIP_DEFLATED) as archive:
                for path in sorted(bundle.rglob("*")):
                    if path.is_file():
                        archive.write(path, path.relative_to(bundle.parent).as_posix())
        elif archive_format == "tar.gz":
            with tarfile.open(destination, "w:gz") as archive:
                archive.add(bundle, arcname=bundle_name)
        else:
            raise ValueError(f"unsupported archive format: {archive_format}")
    return destination


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build local Agul, Agulater, and AgentKube acceptance artifacts."
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / ".tmp" / "acceptance-candidate",
    )
    parser.add_argument("--skip-build", action="store_true")
    args = parser.parse_args()

    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)

    agul_version = tomllib.loads((AGUL / "Cargo.toml").read_text(encoding="utf-8"))[
        "package"
    ]["version"]
    agulater_version = json.loads(
        (AGULATER / "package.json").read_text(encoding="utf-8")
    )["version"]
    agentkube_version = json.loads(
        (ROOT / ".agents" / "package.json").read_text(encoding="utf-8")
    )["version"]
    (
        runtime_platform,
        target,
        archive_format,
        executable,
        bun_target,
    ) = host_release()

    if not args.skip_build:
        run("cargo", "build", "--release", "--locked", cwd=AGUL)
    binary = AGUL / "target" / "release" / executable
    if not binary.is_file():
        raise SystemExit(f"missing Agul binary: {binary}")

    run(
        sys.executable,
        str(AGUL / "scripts" / "package_release.py"),
        "--binary",
        str(binary),
        "--target",
        target,
        "--version",
        agul_version,
        "--format",
        archive_format,
        "--output",
        str(output),
    )
    suffix = ".zip" if archive_format == "zip" else ".tar.gz"
    agul_archive = output / f"agul-v{agul_version}-{target}{suffix}"

    agulater_binary = output / (
        f"agulater-v{agulater_version}-{runtime_platform}"
        + (".exe" if platform.system() == "Windows" else "")
    )
    run(
        "bun",
        "build",
        "--compile",
        "--no-compile-autoload-dotenv",
        "--no-compile-autoload-bunfig",
        f"--target={bun_target}",
        f"--outfile={agulater_binary}",
        "tools/agulater.ts",
        cwd=AGULATER,
    )
    if not agulater_binary.is_file():
        raise SystemExit(f"missing Agulater standalone binary: {agulater_binary}")
    version_check = subprocess.run(
        [str(agulater_binary), "--version"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    if version_check != f"agulater {agulater_version}":
        raise SystemExit(f"unexpected Agulater standalone version: {version_check}")

    agulater_release = package_agulater_release(
        binary=agulater_binary,
        platform_name=runtime_platform,
        version=agulater_version,
        archive_format=archive_format,
        output=output,
    )

    # Bun 1.4 rejects combining --destination and --filename. Its default npm
    # tarball name is stable and already includes the package version.
    agulater_npm_archive = output / f"agulater-{agulater_version}.tgz"
    run(
        "bun",
        "pm",
        "pack",
        "--destination",
        str(output),
        "--ignore-scripts",
        cwd=AGULATER,
    )
    if not agulater_npm_archive.is_file():
        raise SystemExit(f"missing Agulater npm archive: {agulater_npm_archive}")

    runtime_index = output / "releases.json"
    runtime_index.write_text(
        json.dumps(
            {
                "format": "agulater/runtime-releases/v1",
                "releases": [
                    {
                        "version": agul_version,
                        "channel": "next" if "-" in agul_version else "stable",
                        "assets": {
                            runtime_platform: {
                                "path": agul_archive.name,
                                "executable": executable,
                            }
                        },
                    }
                ],
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    manifest = {
        "format": "agentkube/acceptance-candidate/v1",
        "versions": {
            "agul": agul_version,
            "agulater": agulater_version,
            "agentkube": agentkube_version,
        },
        "repositories": {
            "agentkube": git_state(ROOT),
            "agul": git_state(AGUL),
            "agulater": git_state(AGULATER),
        },
        "artifacts": {
            "agul": {
                "path": str(agul_archive),
                "sha256": sha256(agul_archive),
            },
            "agulater": {
                "path": str(agulater_binary),
                "sha256": sha256(agulater_binary),
            },
            "agulater_release": {
                "path": str(agulater_release),
                "sha256": sha256(agulater_release),
            },
            "agulater_npm": {
                "path": str(agulater_npm_archive),
                "sha256": sha256(agulater_npm_archive),
            },
            "runtime_index": str(runtime_index),
        },
    }
    manifest_path = output / "candidate.json"
    manifest_path.write_text(
        json.dumps(manifest, indent=2) + "\n",
        encoding="utf-8",
    )
    print(manifest_path)


if __name__ == "__main__":
    main()
