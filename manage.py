#!/usr/bin/env python
"""Run the canonical Django project from the repository root."""

import os
import sys
from pathlib import Path


def main() -> None:
    """Forward Django management commands to the backend project."""
    backend_dir = Path(__file__).resolve().parent / "backend"
    sys.path.insert(0, str(backend_dir))
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "django_config.settings")

    try:
        from django.core.management import execute_from_command_line
    except ImportError as exc:
        raise ImportError(
            "Couldn't import Django. Is the project virtual environment active?"
        ) from exc

    execute_from_command_line(sys.argv)


if __name__ == "__main__":
    main()
