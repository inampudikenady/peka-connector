"""Validate and inject the requested version into Python package metadata."""

import re
import sys
from pathlib import Path

from app.core.version import validate_connector_version


def main() -> None:
    if len(sys.argv) not in {3, 4}:
        raise SystemExit(
            "usage: prepare_build_version.py VERSION PYPROJECT_PATH [BUILD_MODULE_PATH]"
        )
    try:
        version = validate_connector_version(sys.argv[1])
    except ValueError as exc:
        raise SystemExit(str(exc)) from None
    pyproject_path = Path(sys.argv[2])
    content = pyproject_path.read_text(encoding="utf-8")
    updated, replacements = re.subn(
        r'(?m)^version = "[^"]+"$',
        f'version = "{version}"',
        content,
        count=1,
    )
    if replacements != 1:
        raise SystemExit("could not find exactly one project version in pyproject.toml")
    pyproject_path.write_text(updated, encoding="utf-8")
    if len(sys.argv) == 4:
        build_module_path = Path(sys.argv[3])
        build_module_path.write_text(
            f'"""Generated release identity; do not edit."""\n\nBUILD_VERSION = {version!r}\n',
            encoding="utf-8",
        )


if __name__ == "__main__":
    main()
