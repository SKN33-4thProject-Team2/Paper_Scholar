"""외부 AI API 호출을 담당하는 서비스 패키지."""

import sys
from pathlib import Path


SRC_DIR = Path(__file__).resolve().parent.parent
PROJECT_ROOT = SRC_DIR.parent
MODEL_CONFIG_PATH = SRC_DIR / "config" / "model_config.yaml"

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

__all__ = ["MODEL_CONFIG_PATH", "PROJECT_ROOT", "SRC_DIR"]
