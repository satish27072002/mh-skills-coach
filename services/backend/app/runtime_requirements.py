from __future__ import annotations

import importlib
import subprocess
import sys
from pathlib import Path


_SENTINEL_MODULES = [
    "fastapi",
    "sqlalchemy",
    "langgraph",
    "langchain_openai",
    "pypdf",
    "mcp",
]


def missing_backend_modules() -> list[str]:
    missing: list[str] = []
    for module_name in _SENTINEL_MODULES:
        try:
            importlib.import_module(module_name)
        except ModuleNotFoundError:
            missing.append(module_name)
    return missing


def ensure_backend_requirements(install_missing: bool = False) -> None:
    missing = missing_backend_modules()
    if not missing:
        return
    if install_missing:
        requirements_path = Path(__file__).resolve().parents[1] / "requirements.txt"
        subprocess.check_call(
            [
                sys.executable,
                "-m",
                "pip",
                "install",
                "--user",
                "--break-system-packages",
                "-r",
                str(requirements_path),
            ]
        )
        remaining = missing_backend_modules()
        if not remaining:
            return
        missing = remaining
    raise RuntimeError(
        "Missing backend dependencies: "
        + ", ".join(missing)
        + ". Install services/backend/requirements.txt before running the backend or test suite."
    )
