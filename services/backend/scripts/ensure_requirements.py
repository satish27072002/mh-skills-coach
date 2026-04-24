from __future__ import annotations

import os
import subprocess
import sys

# Ensure the parent (/app) is on sys.path so that "from app.runtime_requirements"
# resolves when this script is launched as "python scripts/ensure_requirements.py".
# Python normally adds the script's own directory to sys.path[0], not the CWD.
_SCRIPT_PARENT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _SCRIPT_PARENT not in sys.path:
    sys.path.insert(0, _SCRIPT_PARENT)

from app.runtime_requirements import ensure_backend_requirements  # noqa: E402


def main() -> int:
    args = sys.argv[1:]
    install_missing = False
    if args and args[0] == "--install-missing":
        install_missing = True
        args = args[1:]
    if args and args[0] == "--":
        args = args[1:]

    ensure_backend_requirements(install_missing=install_missing)

    if args:
        return subprocess.call(args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
