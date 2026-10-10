"""Verify the built artifacts before publishing.

Run after ``python -m build``. Checks three things that must be true of a
payments client that claims zero dependencies and does not redistribute GIMAC's
specification:

1. the specification is in neither artifact;
2. the wheel declares no runtime dependency;
3. the wheel carries ``py.typed`` so type checkers use the inline annotations.
"""

from __future__ import annotations

import sys
import tarfile
import zipfile
from pathlib import Path

DIST = Path(sys.argv[1] if len(sys.argv) > 1 else "dist")
WHEEL = next(DIST.glob("*.whl"))
SDIST = next(DIST.glob("*.tar.gz"))

failures: list[str] = []


def check(label: str, ok: bool, detail: str = "") -> None:
    print(f"  {'PASS' if ok else 'FAIL'}  {label}{f' -- {detail}' if detail else ''}")
    if not ok:
        failures.append(label)


print(f"wheel: {WHEEL.name}")
with zipfile.ZipFile(WHEEL) as zf:
    wheel_names = zf.namelist()
    metadata_name = next(n for n in wheel_names if n.endswith("METADATA"))
    metadata = zf.read(metadata_name).decode("utf-8")

    print("  contents:")
    for name in sorted(wheel_names):
        print(f"    {name}")

    print()
    check(
        "specification is not in the wheel",
        not any("reference" in n or n.endswith((".yaml", ".yml")) for n in wheel_names),
    )
    check(
        "docs/ is not in the wheel",
        not any(n.startswith("docs/") for n in wheel_names),
    )
    check("py.typed marker is shipped", any(n.endswith("gimacpay/py.typed") for n in wheel_names))
    check("console script is declared", "gimacpay" in metadata)

    runtime = [
        line
        for line in metadata.splitlines()
        if line.startswith("Requires-Dist:") and "extra ==" not in line
    ]
    check("no runtime dependencies", not runtime, ", ".join(runtime))

    extras = [line for line in metadata.splitlines() if line.startswith("Requires-Dist:")]
    print(f"  declared requirements (all extras): {len(extras)}")

print()
print(f"sdist: {SDIST.name}")
with tarfile.open(SDIST) as tf:
    sdist_names = tf.getnames()
    check(
        "specification is not in the sdist",
        not any("gimac-api" in n for n in sdist_names),
    )
    check(
        "tests are shipped in the sdist",
        any("/tests/test_" in n for n in sdist_names),
    )

print()
if failures:
    print(f"{len(failures)} check(s) FAILED: {failures}")
    raise SystemExit(1)
print("all artifact checks passed")
