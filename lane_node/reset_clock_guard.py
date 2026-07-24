#!/usr/bin/env python3
"""Offline, audited recovery for the Pi physical-command clock latch."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

from reliable_transport import DurableTransport, default_transport_path


def _require_inactive_service(service):
    result = subprocess.run(
        ["systemctl", "is-active", "--quiet", service],
        timeout=5, check=False)
    if result.returncode == 0:
        raise SystemExit(
            f"{service} is active; stop it before resetting clock authority")
    if result.returncode != 3:
        raise SystemExit(
            f"could not prove {service} is inactive "
            f"(systemctl exit {result.returncode})")


def _require_synchronized_clock():
    result = subprocess.run(
        ["timedatectl", "show", "-p", "NTPSynchronized", "--value"],
        capture_output=True, text=True, timeout=5, check=False)
    if result.returncode != 0 or result.stdout.strip().lower() != "yes":
        raise SystemExit(
            "timedatectl does not report NTPSynchronized=yes")


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--actor-id", required=True, type=int)
    parser.add_argument("--note", required=True)
    parser.add_argument("--service", default="lane-node.service")
    parser.add_argument("--db", type=Path, default=default_transport_path())
    args = parser.parse_args(argv)
    if not sys.platform.startswith("linux"):
        raise SystemExit("clock reset is supported only on the deployed Pi")
    _require_inactive_service(args.service)
    _require_synchronized_clock()
    confirmed = time.time()
    transport = DurableTransport(args.db)
    audit = transport.reset_wall_clock(
        confirmed, args.actor_id, args.note)
    print(json.dumps({
        "ok": True,
        "clock_guard": transport.wall_clock_status(),
        "audit": audit,
    }, sort_keys=True))


if __name__ == "__main__":
    main()
