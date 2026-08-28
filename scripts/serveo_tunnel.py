#!/usr/bin/env python3
"""Maintain a Serveo tunnel and publish its current origin to Google Cloud Storage."""

import os
import re
import signal
import subprocess
import sys
from pathlib import Path

_ORIGIN_PATTERN = re.compile(r"https://[a-zA-Z0-9.-]+\.serveousercontent\.com")
_SSH = "/usr/bin/ssh"


def _publish(origin: str, pointer: str, project: str, gcloud: str) -> None:
    environment = os.environ.copy()
    environment["CLOUDSDK_CORE_PROJECT"] = project
    environment["CLOUDSDK_PYTHON"] = sys.executable
    completed = subprocess.run(  # noqa: S603 - fixed executable and validated destination
        [gcloud, "storage", "cp", "-", pointer, "--quiet"],
        input=f"{origin}\n",
        text=True,
        capture_output=True,
        check=False,
        env=environment,
        timeout=30,
    )
    if completed.returncode:
        message = completed.stderr.strip() or "unknown gcloud error"
        raise RuntimeError(f"pointer publication failed: {message}")


def main() -> int:
    pointer = os.environ["PROFILEPROOF_TUNNEL_POINTER"]
    project = os.environ["PROFILEPROOF_GCP_PROJECT"]
    gcloud = os.environ.get(
        "PROFILEPROOF_GCLOUD_BIN", str(Path.home() / ".local/opt/google-cloud-sdk/bin/gcloud")
    )
    identity = os.environ.get(
        "PROFILEPROOF_TUNNEL_IDENTITY", str(Path.home() / ".ssh/profileproof_serveo_ed25519")
    )
    if not pointer.startswith("gs://profileproof-tunnel-pointer-"):
        raise ValueError("unexpected tunnel pointer bucket")
    if not Path(gcloud).is_file():
        raise FileNotFoundError("Google Cloud CLI is missing")
    if not Path(identity).is_file():
        raise FileNotFoundError("dedicated Serveo SSH identity is missing")

    child = subprocess.Popen(  # noqa: S603 - fixed executable and fixed arguments
        [
            _SSH,
            "-T",
            "-i",
            identity,
            "-o",
            "IdentitiesOnly=yes",
            "-o",
            "StrictHostKeyChecking=accept-new",
            "-o",
            "ServerAliveInterval=30",
            "-o",
            "ServerAliveCountMax=3",
            "-o",
            "ExitOnForwardFailure=yes",
            "-R",
            "80:localhost:8080",
            "serveo.net",
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )

    def terminate(_signum: int, _frame: object) -> None:
        child.terminate()

    signal.signal(signal.SIGTERM, terminate)
    signal.signal(signal.SIGINT, terminate)

    assert child.stdout is not None
    published: str | None = None
    for line in child.stdout:
        print(line.rstrip(), flush=True)
        normalized = line.casefold()
        if "port forwarding for" in normalized and "expired" in normalized:
            print("relay lease expired; reconnecting", flush=True)
            child.terminate()
            break
        match = _ORIGIN_PATTERN.search(line)
        if match and match.group(0) != published:
            published = match.group(0)
            _publish(published, pointer, project, gcloud)
            print(f"published relay origin: {published}", flush=True)
    return child.wait()


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as error:
        print(f"tunnel supervisor failed: {error}", file=sys.stderr, flush=True)
        raise
