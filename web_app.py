"""Academic Paper RAG Chatbot의 Streamlit 실행 파일.

실행 방법
---------
프로젝트 최상위 폴더에서 아래 명령어를 실행한다.

    pip install -r requirements.txt
    streamlit run web_app.py

실제 화면은 ``apps`` 폴더에 기능별로 모듈화되어 있다. 이 파일은 실행 설정,
사이드바 메뉴, 화면 연결만 담당한다.
"""

from __future__ import annotations

import sys
from pathlib import Path

import streamlit as st


PROJECT_ROOT = Path(__file__).resolve().parent
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from apps.chatbot_app import render_chatbot_page
from apps.deep_search_app import render_deep_search_page
from apps.paper_list_app import render_paper_list_page
from apps.search_app import render_search_page
from apps.translation_summary_app import render_translation_summary_page
from apps.ui import apply_global_styles, image_data_url


CHAT_PAGE = "PAPER BOT"

# 챗봇은 라디오 목록에 섞지 않는다. 이 화면이 주인공이라 브랜드 위에 큰 탭으로
# 따로 세우고, 나머지는 아래 목록에 둔다.
SUB_PAGES = {
    "논문 검색": render_search_page,
    "내 서재": render_paper_list_page,
    "논문 번역 및 요약": render_translation_summary_page,
    "딥서치": render_deep_search_page,
}
PAGES = {CHAT_PAGE: render_chatbot_page, **SUB_PAGES}
LOGO_PATH = PROJECT_ROOT / "apps" / "paper_scholar_logo.png"

# 브랜드 위에 앉는 큰 탭. 사이드바의 첫 버튼 하나만 잡는다.
CHAT_TAB_STYLES = """
<style>
/* 브랜드 위에 앉는 큰 탭. 사이드바의 버튼은 이것 하나뿐이다.
   형광에 가까운 파랑 한 겹과 넓은 자간은 폼 버튼처럼 보였다. 색을 한 단계
   눌러 세로로만 흐르게 하고, 그림자는 얇은 윤곽과 넓게 퍼지는 빛 두 겹으로
   나눠 깐다. 글자는 왼쪽으로 붙여 아래 메뉴와 세로선을 맞춘다. */
[data-testid="stSidebar"] .stButton { margin-bottom: 0.45rem; }
[data-testid="stSidebar"] .stButton button {
    width: 100%;
    display: flex;
    align-items: center;
    justify-content: flex-start;
    gap: 0.55rem;
    padding: 0.72rem 0.95rem;
    border: none;
    border-radius: 0.7rem;
    background: linear-gradient(180deg, #2f7df2 0%, #1868dd 100%);
    color: #fff;
    box-shadow:
        0 1px 2px rgba(16, 40, 80, 0.18),
        0 8px 18px -10px rgba(24, 104, 221, 0.65),
        inset 0 1px 0 rgba(255, 255, 255, 0.16);
    transition: transform 0.12s ease, box-shadow 0.18s ease, filter 0.18s ease;
}
/* 로고가 펼친 책이라 같은 결로 맞춘다. 📖 · 📑 · 📚 로 바꿔도 된다. */
[data-testid="stSidebar"] .stButton button::before {
    content: "📄";
    font-size: 1rem;
    line-height: 1;
}
/* 라벨이 남은 폭을 다 먹고 가운데로 가면 표식만 왼쪽에 뜬다. 붙여 세운다. */
[data-testid="stSidebar"] .stButton button > div {
    flex: 0 0 auto;
    justify-content: flex-start;
    text-align: left;
}
[data-testid="stSidebar"] .stButton button p {
    margin: 0;
    text-align: left;
    font-size: 0.86rem;
    font-weight: 600;
    letter-spacing: 0.055em;
}
[data-testid="stSidebar"] .stButton button:hover {
    transform: translateY(-1px);
    filter: saturate(1.04);
    box-shadow:
        0 1px 2px rgba(16, 40, 80, 0.2),
        0 12px 22px -10px rgba(24, 104, 221, 0.7),
        inset 0 1px 0 rgba(255, 255, 255, 0.2);
    color: #fff;
}
[data-testid="stSidebar"] .stButton button:active {
    transform: translateY(0);
    box-shadow:
        0 1px 2px rgba(16, 40, 80, 0.22),
        inset 0 1px 2px rgba(8, 30, 66, 0.18);
}
[data-testid="stSidebar"] .stButton button:focus-visible {
    outline: 2px solid #1868dd;
    outline-offset: 2px;
}

/* 다른 화면에 가 있을 때. 자리와 모양은 그대로 두고 색만 뺀다. */
[data-testid="stSidebar"] .stButton button[kind="secondary"] {
    background: #fff;
    color: #1f3352;
    box-shadow:
        0 1px 2px rgba(16, 40, 80, 0.06),
        inset 0 0 0 1px #dfe4ec;
}
[data-testid="stSidebar"] .stButton button[kind="secondary"]:hover {
    background: #f6f9fe;
    color: #1f3352;
    box-shadow:
        0 2px 6px rgba(16, 40, 80, 0.08),
        inset 0 0 0 1px #c9d6ea;
}
</style>
"""


def _select_sub_page() -> None:
    """아래 목록을 고르면 그쪽으로 넘어간다."""
    if st.session_state.get("menu"):
        st.session_state["page"] = st.session_state["menu"]


def _select_chat_page() -> None:
    """위의 큰 탭을 누르면 챗봇으로 돌아오고 아래 목록의 선택은 풀린다."""
    st.session_state["page"] = CHAT_PAGE
    st.session_state["menu"] = None


def main() -> None:
    """사이드바에서 선택한 Streamlit 화면을 실행한다."""
    st.set_page_config(
        page_title="Academic Paper RAG Chatbot",
        page_icon="🎓",
        layout="wide",
        initial_sidebar_state="expanded",
    )
    apply_global_styles()
    logo_src = image_data_url(str(LOGO_PATH), LOGO_PATH.stat().st_mtime)
    if "page" not in st.session_state:
        st.session_state["page"] = CHAT_PAGE

    with st.sidebar:
        st.markdown(CHAT_TAB_STYLES, unsafe_allow_html=True)
        # on_click 으로 넘긴다. if st.button(...) 안에서 상태를 바꾸면 버튼은
        # 이미 이전 상태로 그려진 뒤라 색이 한 박자 늦는다. 콜백은 다시 그리기
        # 전에 돌아서 다음 실행이 처음부터 챗봇 상태로 시작한다.
        st.button(
            CHAT_PAGE,
            use_container_width=True,
            type="primary" if st.session_state["page"] == CHAT_PAGE else "secondary",
            on_click=_select_chat_page,
        )
        st.markdown(
            f"""
            <div class="sidebar-brand">
                <span class="sidebar-brand-icon">
                    <img src="{logo_src}" alt="Paper Scholar 책 로고">
                </span>
                <div>
                    <strong>Paper Scholar</strong>
                    <small>Academic RAG Assistant</small>
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )
        st.radio(
            "메뉴",
            options=list(SUB_PAGES),
            index=None,
            key="menu",
            on_change=_select_sub_page,
            label_visibility="collapsed",
        )
        st.markdown(
            """
            <div class="sidebar-help">
                <strong>이용 순서</strong><br>
                PAPER BOT 한 곳에서 다 됩니다.<br>단계별로 보려면 아래 메뉴
            </div>
            """,
            unsafe_allow_html=True,
        )

    PAGES[st.session_state["page"]]()


if __name__ == "__main__":
    main()
