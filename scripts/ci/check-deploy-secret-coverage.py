#!/usr/bin/env python3
"""Fail when a deploy lane silently stops passing a secret.

deploy/backend.cloudbuild.yaml binds each secret through a substitution:

    add_secret "${_SOME_THING_SECRET}" "SOME_THING"

Every substitution defaults to "" and `add_secret` skips empties, so a lane
that never passes one produces a service with that environment variable simply
absent. Nothing fails. Nothing logs. The feature that reads it just behaves as
though it was never configured.

That is how UAT test phone numbers broke: the UAT lane never passed
_HUSHH_UAT_PHONE_TEST_CHALLENGE_SECRET_SECRET, so the challenge key silently
fell back to APP_SIGNING_KEY.

Many omissions are deliberate -- production must not carry UAT test numbers,
dev must not carry production ones. So this does not demand every lane pass
every secret. It pins the omissions that exist today in
`config/deploy-env-coverage.json` and fails on a NEW one, which is the
case nobody notices.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
CLOUDBUILD = REPO_ROOT / "deploy" / "backend.cloudbuild.yaml"
BASELINE = REPO_ROOT / "config" / "deploy-env-coverage.json"
WORKFLOWS = REPO_ROOT / ".github" / "workflows"

_BIND = re.compile(r'add_secret "\$\{(_[A-Z0-9_]+_SECRET)\}"')


def bound_substitutions() -> list[str]:
    found = _BIND.findall(CLOUDBUILD.read_text(encoding="utf-8"))
    # Preserve declaration order; de-duplicate.
    seen: dict[str, None] = {}
    for name in found:
        seen.setdefault(name, None)
    return list(seen)


def passed_by(workflow: Path) -> set[str]:
    text = workflow.read_text(encoding="utf-8")
    return {name for name in bound_substitutions() if f"{name}=" in text}


def main() -> int:
    if not CLOUDBUILD.exists():
        print(f"missing {CLOUDBUILD}", file=sys.stderr)
        return 2
    baseline = json.loads(BASELINE.read_text(encoding="utf-8"))
    bound = bound_substitutions()
    failures: list[str] = []

    for lane, expected in baseline["lanes"].items():
        workflow = WORKFLOWS / lane
        if not workflow.exists():
            failures.append(f"{lane}: workflow not found")
            continue
        passed = passed_by(workflow)
        actual_absent = {name for name in bound if name not in passed}
        allowed_absent = set(expected["absent"])

        for name in sorted(actual_absent - allowed_absent):
            failures.append(
                f"{lane}: {name} is bound in backend.cloudbuild.yaml but this lane "
                f"does not pass it, so the service runs without it and nothing fails. "
                f"Pass it, or record it in {BASELINE.relative_to(REPO_ROOT)} with a reason."
            )
        for name in sorted(allowed_absent - actual_absent):
            failures.append(
                f"{lane}: {name} is recorded as deliberately absent but the lane now "
                f"passes it. Remove it from {BASELINE.relative_to(REPO_ROOT)}."
            )
        for name in sorted(allowed_absent - set(bound)):
            failures.append(
                f"{lane}: {name} is recorded as deliberately absent but is no longer "
                f"bound by backend.cloudbuild.yaml. Remove the stale entry."
            )

    if failures:
        print("Deploy secret coverage drifted:\n", file=sys.stderr)
        for failure in failures:
            print(f"  - {failure}", file=sys.stderr)
        return 1

    lanes = ", ".join(baseline["lanes"])
    print(f"Deploy secret coverage OK: {len(bound)} bound secrets checked across {lanes}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
