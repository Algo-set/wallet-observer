"""Snapshot and offline policy analysis commands."""

import argparse
import asyncio
import json
import os
import sys
import tempfile
import time
from pathlib import Path

from ._validation import ObserverError
from .observer import observe
from .policy import analyze
from .types import ObserverConfig, PortfolioPolicy, PortfolioSnapshot, Record

MAX_INPUT_BYTES = 8 * 1024 * 1024


def _pairs(items):
    result = {}
    for key, value in items:
        if key in result:
            raise ObserverError("duplicate_json_field")
        result[key] = value
    return result


def read_json(path: Path, model: type[Record]) -> Record:
    try:
        with path.open("rb") as source:
            content = source.read(MAX_INPUT_BYTES + 1)
        if len(content) > MAX_INPUT_BYTES:
            raise ObserverError("input_too_large")
        data = json.loads(content, object_pairs_hook=_pairs)
        return model.from_dict(data)
    except (OSError, ValueError, RecursionError):
        raise ObserverError("invalid_input_file") from None


def write_atomic(path: Path, value: Record):
    content = (value.to_json() + "\n").encode()
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
            dir=path.parent, prefix=".wallet-observer-", delete=False
        ) as out:
            temporary = Path(out.name)
            out.write(content)
            out.flush()
            os.fsync(out.fileno())
        os.replace(temporary, path)
    except OSError:
        raise ObserverError("output_write_failed") from None
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Read-only wallet observation and policy reports")
    sub = parser.add_subparsers(dest="command", required=True)
    snapshot = sub.add_parser("snapshot")
    snapshot.add_argument("config", type=Path)
    snapshot.add_argument("output", type=Path)
    policy = sub.add_parser("analyze")
    policy.add_argument("snapshot", type=Path)
    policy.add_argument("policy", type=Path)
    policy.add_argument("output", type=Path, nargs="?")
    args = parser.parse_args(argv)
    try:
        if args.command == "snapshot":
            value = asyncio.run(observe(read_json(args.config, ObserverConfig)))
        else:
            value = analyze(
                read_json(args.snapshot, PortfolioSnapshot),
                read_json(args.policy, PortfolioPolicy),
                time.time_ns() // 1_000_000,
            )
        if args.output is not None:
            write_atomic(args.output, value)
        else:
            print(value.to_json())
        return 0
    except ObserverError as error:
        print(str(error), file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        return 130
    except Exception:
        print("operation_failed", file=sys.stderr)
        return 2
