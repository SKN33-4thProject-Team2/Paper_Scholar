"""번역 완료 논문의 전문 번역본과 요약본 표시 화면."""

from __future__ import annotations

from html import escape
from pathlib import Path
from typing import Any

import streamlit as st

from apps.ui import normalize_math, render_page_heading


PROJECT_ROOT = Path(__file__).resolve().parent.parent
OUTPUT_DIR = PROJECT_ROOT / "data" / "paper_list" / "processed_outputs"
TRANSLATION_SUFFIX = "_full_translated"
SUMMARY_SUFFIX = "_summary"


@st.cache_data(show_spinner=False)
def _read_markdown(path: str, modified_time: float) -> str:
    del modified_time
    # 이미 만들어 둔 요약본은 \( \) 표기라 화면에 뿌리기 직전에 맞춘다.
    return normalize_math(Path(path).read_text(encoding="utf-8"))


def _title(artifact: dict[str, Any]) -> str:
    preferred = artifact.get("translation") or artifact.get("summary")
    if preferred:
        path = Path(preferred)
        content = _read_markdown(str(path), path.stat().st_mtime)
        for line in content.splitlines():
            if line.startswith("# "):
                title = line[2:].strip().removeprefix("원제:").strip()
                return title.removesuffix(" 요약본").strip()
    return str(artifact["key"]).replace("_", " ")


def _load_artifacts() -> list[dict[str, Any]]:
    if not OUTPUT_DIR.exists():
        return []
    grouped: dict[str, dict[str, Any]] = {}
    for path in OUTPUT_DIR.glob("*.md"):
        if path.stem.endswith(TRANSLATION_SUFFIX):
            key = path.stem[: -len(TRANSLATION_SUFFIX)]
            grouped.setdefault(key, {"key": key})["translation"] = path
        elif path.stem.endswith(SUMMARY_SUFFIX):
            key = path.stem[: -len(SUMMARY_SUFFIX)]
            grouped.setdefault(key, {"key": key})["summary"] = path
    artifacts = list(grouped.values())
    for artifact in artifacts:
        artifact["title"] = _title(artifact)
    return sorted(artifacts, key=lambda item: item["title"].lower())


def _document_headings(markdown: str) -> list[tuple[int, str]]:
    """문서 탐색용으로 2·3단계 제목만 추출한다."""
    headings: list[tuple[int, str]] = []
    for line in markdown.splitlines():
        stripped = line.strip()
        if stripped.startswith("### "):
            headings.append((3, stripped[4:].strip()))
        elif stripped.startswith("## "):
            headings.append((2, stripped[3:].strip()))
    return headings


def _show_markdown(label: str, path: Path | None, reader_key: str) -> None:
    if path is None or not path.exists():
        st.warning(f"{label} 파일이 없습니다.")
        return
    content = _read_markdown(str(path), path.stat().st_mtime)
    headings = _document_headings(content)
    if headings:
        with st.expander("문서 구성 보기"):
            for level, heading in headings[:24]:
                indent = "&nbsp;&nbsp;&nbsp;&nbsp;" if level == 3 else ""
                st.markdown(f"{indent}• {escape(heading)}", unsafe_allow_html=True)
    with st.container(border=True, key=reader_key):
        st.markdown(content)


def render_translation_summary_page() -> None:
    """체크한 번역본과 요약본을 Markdown으로 표시한다."""
    render_page_heading(
        "논문 번역 및 요약",
        "번역이 완료된 논문의 전문 번역본과 구조화 요약본을 확인합니다.",
    )
    artifacts = _load_artifacts()
    if not artifacts:
        st.info("표시할 번역 또는 요약 파일이 없습니다.")
        return

    artifact_by_key = {artifact["key"]: artifact for artifact in artifacts}
    selected_key = st.selectbox(
        f"번역 완료 논문 ({len(artifacts)}개)",
        options=list(artifact_by_key),
        format_func=lambda key: artifact_by_key[key]["title"],
    )
    selected = artifact_by_key[selected_key]
    has_translation = "translation" in selected
    has_summary = "summary" in selected
    st.markdown(
        f"""
        <div class="paper-detail-card">
            <h2 title="{escape(str(selected['title']))}">{escape(str(selected['title']))}</h2>
            <div class="paper-meta">
                <span class="document-status {'status-ready' if has_summary else 'status-missing'}">
                    요약본 {'있음' if has_summary else '없음'}
                </span>
                <span class="document-status {'status-ready' if has_translation else 'status-missing'}">
                    번역본 {'있음' if has_translation else '없음'}
                </span>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    summary_tab, translation_tab = st.tabs(["요약본", "전체 번역본"])
    with summary_tab:
        _show_markdown("논문 요약본", selected.get("summary"), "document_reader_summary")
    with translation_tab:
        _show_markdown(
            "논문 번역본",
            selected.get("translation"),
            "document_reader_translation",
        )
