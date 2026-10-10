"""Command line entry point: ``gimacpay``.

Deliberately conservative. Sending money from a shell is easy to do by
accident, so :command:`send` refuses to act without an explicit ``--confirm``,
and :command:`build` prints the payload without sending anything.

Usage::

    gimacpay intents                 # what the specification defines
    gimacpay intents mobile_transfer # required fields for one intent
    gimacpay doctor                  # check config and authenticate
    gimacpay build --intent mobile_transfer --amount 500 --walletsource ... \
                   --walletdestination ... --tomember 22001 --ref ORD-1
    gimacpay send  ... --confirm
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Sequence
from typing import Any

from . import __version__
from .builders import build as build_request
from .client import GimacPayClient
from .errors import GimacPayError, PaymentStateUnknown
from .intents import ALL_INTENTS, REQUIRED_FIELDS, required_fields

__all__ = ["main"]

_ENV_PREFIX = "GIMACPAY_"

#: Fields the CLI passes through as integers rather than strings.
_INT_FIELDS = frozenset({"amount", "validityduration", "pagesize", "firstelement"})


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="gimacpay",
        description="Client for the GIMACPAY participant API (CEMAC).",
    )
    parser.add_argument("--version", action="version", version=f"gimacpay {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    intents = sub.add_parser("intents", help="list the intents in specification 1.10")
    intents.add_argument("intent", nargs="?", help="show the required fields for one intent")

    sub.add_parser("doctor", help="check configuration and authenticate")

    for name, help_text in (
        ("build", "build a request and print it, without sending"),
        ("send", "send a request (requires --confirm)"),
    ):
        cmd = sub.add_parser(name, help=help_text)
        cmd.add_argument("--intent", required=True)
        cmd.add_argument("--ref", required=True, dest="issuertrxref")
        cmd.add_argument("--amount", type=int)
        cmd.add_argument("--currency", default="950")
        cmd.add_argument("--tomember")
        cmd.add_argument("--walletsource")
        cmd.add_argument("--walletdestination")
        cmd.add_argument("--sendermobile")
        cmd.add_argument("--receivermobile")
        cmd.add_argument("--validityduration", type=int)
        cmd.add_argument("--description")
        cmd.add_argument("--extra", help="extra fields as a JSON object")
        cmd.add_argument(
            "--wait",
            type=float,
            default=0.0,
            help="seconds to follow the payment to a terminal state",
        )
        if name == "send":
            cmd.add_argument(
                "--confirm",
                action="store_true",
                help="required: without it nothing is sent",
            )

    return parser


def _client_from_env() -> GimacPayClient:
    """Build a client from ``GIMACPAY_*`` environment variables."""
    missing = [
        key
        for key in ("CLIENT_ID", "CLIENT_SECRET", "USERNAME", "PASSWORD")
        if not os.environ.get(_ENV_PREFIX + key)
    ]
    if missing:
        raise SystemExit(
            "missing environment variables: " + ", ".join(_ENV_PREFIX + key for key in missing)
        )

    return GimacPayClient(
        base_url=os.environ.get(_ENV_PREFIX + "BASE_URL", None) or None or "",
        client_id=os.environ[_ENV_PREFIX + "CLIENT_ID"],
        client_secret=os.environ[_ENV_PREFIX + "CLIENT_SECRET"],
        username=os.environ[_ENV_PREFIX + "USERNAME"],
        password=os.environ[_ENV_PREFIX + "PASSWORD"],
        default_dial_code=os.environ.get(_ENV_PREFIX + "DIAL_CODE"),
    )


def _payload(args: argparse.Namespace) -> dict[str, Any]:
    fields: dict[str, Any] = {
        "issuertrxref": args.issuertrxref,
        "amount": args.amount,
        "currency": args.currency,
        "tomember": args.tomember,
        "walletsource": args.walletsource,
        "walletdestination": args.walletdestination,
        "sendermobile": args.sendermobile,
        "receivermobile": args.receivermobile,
        "validityduration": args.validityduration,
        "description": args.description,
    }
    if args.extra:
        try:
            extra = json.loads(args.extra)
        except json.JSONDecodeError as exc:
            raise SystemExit(f"--extra is not valid JSON: {exc}") from exc
        if not isinstance(extra, dict):
            raise SystemExit("--extra must be a JSON object")
        fields.update(extra)

    return build_request(args.intent, **{k: v for k, v in fields.items() if v is not None})


def _cmd_intents(intent: str | None) -> int:
    if intent:
        if intent not in ALL_INTENTS:
            print(f"unknown intent {intent!r} in specification 1.10", file=sys.stderr)
            print("known intents:", ", ".join(sorted(ALL_INTENTS)), file=sys.stderr)
            return 1
        print(f"{intent}:")
        for name in required_fields(intent):
            print(f"  - {name}")
        return 0

    for name in sorted(ALL_INTENTS):
        fields = REQUIRED_FIELDS.get(name)
        suffix = f"  ({len(fields)} required)" if fields else "  (no builder; use build())"
        print(f"{name}{suffix}")
    print(f"\n{len(ALL_INTENTS)} intents, specification version 1.10", file=sys.stderr)
    return 0


def _cmd_doctor() -> int:
    client = _client_from_env()
    print(f"base_url : {client.base_url}")
    print(f"username : {client.username}")
    print("authenticating...")
    client.authenticate()
    print("OK: authenticated")
    return 0


def _cmd_build(args: argparse.Namespace) -> int:
    print(json.dumps(_payload(args), indent=2, ensure_ascii=False))
    return 0


def _cmd_send(args: argparse.Namespace) -> int:
    if not args.confirm:
        print(
            "refusing to send without --confirm.\n"
            "Review the payload first with:\n"
            "  gimacpay build ...",
            file=sys.stderr,
        )
        return 2

    client = _client_from_env()
    payload = _payload(args)

    if args.wait > 0:
        payment = client.send_and_resolve(payload, timeout=args.wait)
    else:
        payment = client.send_payment(payload)

    print(json.dumps(payment.raw, indent=2, ensure_ascii=False))
    print(f"\nstate: {payment.state}", file=sys.stderr)
    if not payment.is_terminal:
        print(
            f"note: not terminal. Inquire with:\n  issuertrxref={payment.issuertrxref}",
            file=sys.stderr,
        )
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)

    handlers = {
        "intents": lambda: _cmd_intents(getattr(args, "intent", None)),
        "doctor": _cmd_doctor,
        "build": lambda: _cmd_build(args),
        "send": lambda: _cmd_send(args),
    }

    try:
        return handlers[args.command]()
    except PaymentStateUnknown as exc:
        print(f"STATE UNKNOWN: {exc}", file=sys.stderr)
        print("the payment is not failed -- inquire before acting", file=sys.stderr)
        return 3
    except GimacPayError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
