"""테스트 패키지의 공통 경로 설정."""

import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
SRC_DIR = PROJECT_ROOT / "src"

for module_path in (PROJECT_ROOT, SRC_DIR):
    if str(module_path) not in sys.path:
        sys.path.insert(0, str(module_path))

__all__ = ["PROJECT_ROOT", "SRC_DIR"]
