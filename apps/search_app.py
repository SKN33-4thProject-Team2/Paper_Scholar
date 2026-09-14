"""ArXiv 논문 검색과 선택 저장 화면."""

from __future__ import annotations

from html import escape
from pathlib import Path
from typing import Any
from urllib.parse import quote

import streamlit as st

from apps.ui import image_data_url, render_page_heading
from feature.search import ArxivSearchBot


SEARCH_RESULTS_KEY = "arxiv_search_results"
LOGO_PATH = Path(__file__).with_name("paper_scholar_logo.png")


@st.cache_resource(show_spinner=False)
def _get_search_bot() -> ArxivSearchBot:
    return ArxivSearchBot()


def render_search_page() -> None:
    """검색 결과를 보여주고 사용자가 선택한 논문만 저장한다."""
    logo_src = image_data_url(str(LOGO_PATH), LOGO_PATH.stat().st_mtime)
    st.markdown(
        f"""
        <div class="scholar-hero">
            <img class="scholar-logo-image" src="{logo_src}" alt="Paper Scholar">
            <p>학술 논문을 검색하고 필요한 자료를 내 서재에 저장하세요.</p>
        </div>
        """,
        unsafe_allow_html=True,
    )

    with st.form("arxiv_search_form"):
        search_column, button_column = st.columns([8, 1.35])
        with search_column:
            query = st.text_input(
                "논문 검색",
                placeholder="논문 제목, 키워드 또는 연구 주제를 입력하세요",
                label_visibility="collapsed",
            )
        with button_column:
            search_clicked = st.form_submit_button(
                "검색", type="primary", use_container_width=True
            )
        with st.expander("검색 옵션"):
            first, second = st.columns(2)
            with first:
                max_results = st.slider("검색 개수", 1, 15, 5)
            with second:
                sort_label = st.selectbox("정렬", ["관련도순", "최신순"])

    if search_clicked:
        if not query.strip():
            st.warning("검색어를 입력해 주세요.")
        else:
            sort_by = "n" if sort_label == "최신순" else "r"
            try:
                with st.spinner("ArXiv에서 논문을 검색하고 있습니다..."):
                    papers = _get_search_bot().search_papers(
                        query.strip(), sort_by=sort_by, max_results=max_results
                    )
                st.session_state[SEARCH_RESULTS_KEY] = papers
                if not papers:
                    st.info("검색 결과가 없습니다.")
            except Exception as exc:
                st.session_state[SEARCH_RESULTS_KEY] = []
                st.error(f"논문 검색 중 오류가 발생했습니다: {exc}")

    papers: list[dict[str, Any]] = st.session_state.get(SEARCH_RESULTS_KEY, [])
    if not papers:
        return

    render_page_heading(
        f"검색 결과 {len(papers)}개",
        "논문 제목을 누르면 arXiv 원문 페이지가 열립니다.",
    )
    paper_by_id = {paper["id"]: paper for paper in papers}
    selected_ids: list[str] = []

    for paper in papers:
        select_column, result_column = st.columns([0.55, 9.45])
        with select_column:
            if st.checkbox(
                "선택", key=f"save_paper_{paper['id']}", label_visibility="collapsed"
            ):
                selected_ids.append(paper["id"])
        with result_column:
            abstract = str(paper.get("summary") or "초록 정보가 없습니다.")
            preview = abstract if len(abstract) <= 420 else f"{abstract[:420].rstrip()}…"
            arxiv_url = f"https://arxiv.org/abs/{quote(str(paper['id']))}"
            st.markdown(
                f"""
                <div class="result-card">
                    <a class="result-title" href="{arxiv_url}" target="_blank">
                        {escape(str(paper['title']))}
                    </a>
                    <p class="result-meta">
                        {escape(str(paper.get('authors') or '저자 정보 없음'))} · arXiv:{escape(str(paper['id']))}
                    </p>
                    <p class="result-abstract">{escape(preview)}</p>
                </div>
                """,
                unsafe_allow_html=True,
            )
            with st.expander("초록 전체 보기"):
                st.write(abstract)

    save_column, count_column = st.columns([2.2, 7.8])
    with save_column:
        save_clicked = st.button(
            "선택한 논문 저장",
            type="primary",
            disabled=not selected_ids,
            use_container_width=True,
        )
    with count_column:
        if selected_ids:
            st.caption(f"{len(selected_ids)}개 논문을 선택했습니다.")

    if save_clicked:
        try:
            selected = [paper_by_id[paper_id] for paper_id in selected_ids]
            message = _get_search_bot().save_papers(selected)
            st.success(message)
            st.info("저장한 논문은 ‘내 서재’에서 확인할 수 있습니다.")
        except Exception as exc:
            st.error(f"논문 저장 중 오류가 발생했습니다: {exc}")
