#!/usr/bin/env bash

set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON_BIN="${PAPER_SCHOLAR_PYTHON:-python}"

# 로컬 점검이 LangSmith 외부 전송을 기다리지 않도록 비활성화합니다.
export LANGSMITH_TRACING=false
export LANGCHAIN_TRACING_V2=false

cd "$PROJECT_DIR"

"$PYTHON_BIN" backend/manage.py check --settings=django_config.test_settings
"$PYTHON_BIN" backend/manage.py test scholar --settings=django_config.test_settings
"$PYTHON_BIN" -m unittest \
  tests.test_search_list_repository \
  tests.test_v2_mysql_sync \
  tests.test_orchestration \
  tests.test_translation_markdown_service \
  tests.test_evaluation_frameworks \
  tests.test_extractor_mysql_sync

cd frontend
npm run lint
npm run build
