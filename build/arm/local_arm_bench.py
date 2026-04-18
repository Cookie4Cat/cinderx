#!/usr/bin/env python3
"""
Local helper for syncing the current checkout to the ARM host and invoking the
remote benchmark runner.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
REMOTE_HOST = "my-server"
REMOTE_WORKSPACE = "/root/src/cinderx-meta-main"
REMOTE_ARCHIVE = "/root/src/cinderx-meta-main.tar.gz"
REMOTE_RUNNER = f"{REMOTE_WORKSPACE}/build/arm/remote_pyperf_runner.py"
LOCAL_DEPS = REPO_ROOT / "build" / "arm" / "deps"
REMOTE_DEPS = "/root/src/cinderx-deps"
REMOTE_DEPS_ARCHIVE = "/root/src/cinderx-deps.tar.gz"


def run(cmd: list[str]) -> None:
    print("+", " ".join(cmd))
    subprocess.run(cmd, check=True)


def make_archive() -> Path:
    fd, archive_name = tempfile.mkstemp(prefix="cinderx-meta-main-", suffix=".tar.gz")
    os.close(fd)
    archive = Path(archive_name)

    def include(path: Path) -> bool:
        parts = path.relative_to(REPO_ROOT).parts
        if not parts:
            return True
        if parts[0] == ".git":
            return False
        if parts[0] == "scratch":
            return False
        if "__pycache__" in parts:
            return False
        return True

    with tarfile.open(archive, "w:gz") as tf:
        for path in REPO_ROOT.rglob("*"):
            if not include(path):
                continue
            arcname = path.relative_to(REPO_ROOT)
            tf.add(path, arcname=str(arcname), recursive=False)
    return archive


def sync() -> None:
    archive = make_archive()
    try:
        run(["ssh", REMOTE_HOST, "mkdir", "-p", "/root/src"])
        run(["scp", str(archive), f"{REMOTE_HOST}:{REMOTE_ARCHIVE}"])
        extract = (
            f"rm -rf {REMOTE_WORKSPACE} && mkdir -p {REMOTE_WORKSPACE} && "
            f"tar -xzf {REMOTE_ARCHIVE} -C {REMOTE_WORKSPACE}"
        )
        run(["ssh", REMOTE_HOST, extract])
    finally:
        archive.unlink(missing_ok=True)


def sync_deps() -> None:
    if not LOCAL_DEPS.exists():
        raise FileNotFoundError(f"missing local deps dir: {LOCAL_DEPS}")
    fd, archive_name = tempfile.mkstemp(prefix="cinderx-deps-", suffix=".tar.gz")
    os.close(fd)
    archive = Path(archive_name)
    try:
        with tarfile.open(archive, "w:gz") as tf:
            for path in LOCAL_DEPS.rglob("*"):
                parts = path.relative_to(LOCAL_DEPS).parts
                if ".git" in parts or "__pycache__" in parts:
                    continue
                arcname = path.relative_to(LOCAL_DEPS)
                tf.add(path, arcname=str(arcname), recursive=False)
        run(["ssh", REMOTE_HOST, "mkdir", "-p", "/root/src"])
        run(["scp", str(archive), f"{REMOTE_HOST}:{REMOTE_DEPS_ARCHIVE}"])
        extract = (
            f"rm -rf {REMOTE_DEPS} && mkdir -p {REMOTE_DEPS} && "
            f"tar -xzf {REMOTE_DEPS_ARCHIVE} -C {REMOTE_DEPS}"
        )
        run(["ssh", REMOTE_HOST, extract])
    finally:
        archive.unlink(missing_ok=True)


def remote(args: list[str]) -> None:
    cmd = ["ssh", REMOTE_HOST, "/opt/python-3.14/bin/python3.14", REMOTE_RUNNER, *args]
    run(cmd)


def main() -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("sync")
    sub.add_parser("sync-deps")
    sub.add_parser("build")

    bench = sub.add_parser("bench")
    bench.add_argument("--suite", choices=["target", "guardrail"], default="target")
    bench.add_argument("--mode", choices=["fast", "rigorous"], default="fast")
    bench.add_argument("--tag", default="adhoc")

    sub.add_parser("preflight")
    sub.add_parser("profile")

    args = parser.parse_args()
    if args.cmd == "sync":
        sync()
    elif args.cmd == "sync-deps":
        sync_deps()
    elif args.cmd == "build":
        remote(["build"])
    elif args.cmd == "bench":
        remote(["bench", "--suite", args.suite, "--mode", args.mode, "--tag", args.tag])
    elif args.cmd == "preflight":
        remote(["preflight"])
    elif args.cmd == "profile":
        remote(["profile"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
