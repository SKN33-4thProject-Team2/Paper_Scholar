"""Streamlit 화면에서 공통으로 사용하는 디자인 요소."""

from __future__ import annotations

import base64
import re
from html import escape
from pathlib import Path

import streamlit as st


@st.cache_data(show_spinner=False)
def image_data_url(path: str, modified_time: float) -> str:
    """로컬 이미지를 브라우저에서 사용할 수 있는 data URL로 변환한다."""
    del modified_time
    encoded = base64.b64encode(Path(path).read_bytes()).decode("ascii")
    return f"data:image/png;base64,{encoded}"


# 모델은 수식을 \( \) 와 \[ \] 로 감싸 오는데, Streamlit 의 마크다운은 $ 만 수식으로
# 읽는다. 그대로 두면 괄호만 남고 \frac 이나 \mathbb{R} 이 날것으로 보인다.
# 요약본 파일과 딥서치 답변 양쪽에서 같은 일이 생겨 여기에 모아 둔다.
DISPLAY_MATH_PATTERN = re.compile(r"\\\[(.+?)\\\]", re.DOTALL)
INLINE_MATH_PATTERN = re.compile(r"\\\((.+?)\\\)", re.DOTALL)


def _one_line(body: str) -> str:
    """수식 안의 줄바꿈을 없앤다.

    Streamlit 은 $$ 안에 줄바꿈이 있으면 수식으로 읽지 않고, 그러면 마크다운이
    그 줄들을 앞뒤 문단과 한 덩어리로 합쳐 버린다. 수식이 통째로 날것으로 보이고
    소제목까지 문장 사이에 끼는 이유가 이것이다. LaTeX 은 공백을 무시하므로
    한 줄로 눌러도 식의 뜻은 그대로다.
    """
    return " ".join(body.split())


def normalize_math(markdown: str) -> str:
    """LaTeX 식 구분자를 Streamlit 이 읽는 달러 표기로 바꾼다."""
    markdown = DISPLAY_MATH_PATTERN.sub(lambda m: f"$${_one_line(m.group(1))}$$", markdown)
    return INLINE_MATH_PATTERN.sub(lambda m: f"${_one_line(m.group(1))}$", markdown)


def apply_global_styles() -> None:
    """Google Scholar의 간결한 검색 경험을 참고한 공통 스타일을 적용한다."""
    st.markdown(
        """
        <style>
        :root {
            --scholar-blue: #1a73e8;
            --scholar-blue-dark: #1558b0;
            --scholar-green: #2e7d32;
            --scholar-text: #202124;
            --scholar-muted: #5f6368;
            --scholar-border: #dadce0;
            --scholar-surface: #f8f9fa;
        }
        .stApp { background: #fff; color: var(--scholar-text); }
        .block-container { max-width: 1120px; padding-top: 2.2rem; padding-bottom: 4rem; }
        [data-testid="stSidebar"] {
            background: var(--scholar-surface);
            border-right: 1px solid var(--scholar-border);
        }
        [data-testid="stSidebar"] label[data-testid="stRadioOption"] {
            padding:.62rem .8rem; margin:.12rem 0; border-left:4px solid transparent;
            border-radius:0 .5rem .5rem 0; transition:background .15s ease, border-color .15s ease;
        }
        [data-testid="stSidebar"] label[data-testid="stRadioOption"] > div > div > div:first-child {
            display:none;
        }
        [data-testid="stSidebar"] label[data-testid="stRadioOption"]:hover {
            background:#eef3fb;
        }
        [data-testid="stSidebar"] label[data-testid="stRadioOption"][data-selected="true"] {
            background:#e8f0fe; border-left-color:var(--scholar-blue);
        }
        [data-testid="stSidebar"] label[data-testid="stRadioOption"][data-selected="true"] p {
            color:var(--scholar-blue-dark); font-weight:600;
        }
        .sidebar-brand { display:flex; align-items:center; gap:.7rem; padding:.4rem 0 1.35rem; }
        .sidebar-brand-icon {
            position:relative; display:block; width:2.3rem; height:2.3rem; flex:0 0 2.3rem;
            border-radius:50%; background:#e8f0fe; overflow:hidden;
        }
        .sidebar-brand-icon img {
            position:absolute; width:6rem; max-width:none; height:auto;
            left:-.28rem; top:-.78rem;
        }
        .sidebar-brand strong, .sidebar-brand small { display:block; }
        .sidebar-brand small { color:var(--scholar-muted); font-size:.72rem; margin-top:.1rem; }
        .sidebar-help {
            margin-top:2rem; padding:.9rem 1rem; border-top:1px solid var(--scholar-border);
            color:var(--scholar-muted); font-size:.78rem; line-height:1.7;
        }
        .scholar-hero { text-align:center; padding:3.8rem 1rem 1.8rem; }
        .scholar-logo-image {
            display:block; width:min(680px, 100%); height:220px; object-fit:cover;
            object-position:center; margin:0 auto; border-radius:1rem;
        }
        .scholar-logo {
            margin:0; font-size:clamp(2.5rem, 6vw, 4.2rem); font-weight:500;
            letter-spacing:-.08em; line-height:1.08;
        }
        .scholar-logo .blue { color:#4285f4; }
        .scholar-logo .red { color:#ea4335; }
        .scholar-logo .yellow { color:#fbbc05; }
        .scholar-logo .green { color:#34a853; }
        .scholar-logo .dark { color:#5f6368; letter-spacing:-.05em; margin-left:.1em; }
        .scholar-hero p { color:var(--scholar-muted); margin:.75rem 0 0; font-size:.98rem; }
        .page-heading {
            padding:.35rem 0 1.25rem; border-bottom:1px solid var(--scholar-border);
            margin-bottom:1.5rem;
        }
        .page-heading h1 { font-size:1.72rem; font-weight:500; margin:0; color:var(--scholar-text); }
        .page-heading p { color:var(--scholar-muted); margin:.45rem 0 0; }
        .result-card { padding:1rem 0 1.15rem; border-bottom:1px solid #eceff1; }
        .result-title {
            color:var(--scholar-blue); font-size:1.15rem; font-weight:500;
            line-height:1.35; text-decoration:none;
        }
        .result-title:hover { color:var(--scholar-blue-dark); text-decoration:underline; }
        .result-meta { color:var(--scholar-green); font-size:.85rem; margin:.35rem 0; }
        .result-abstract { color:#3c4043; font-size:.9rem; line-height:1.55; margin:0; }
        .paper-detail-card {
            border:1px solid var(--scholar-border); border-radius:.65rem; padding:1.35rem 1.5rem;
            margin:1rem 0; background:#fff; box-shadow:0 1px 2px rgba(60,64,67,.08);
        }
        .paper-detail-card h2 {
            display:-webkit-box; overflow:hidden; -webkit-box-orient:vertical; -webkit-line-clamp:2;
            color:var(--scholar-blue); font-size:1.35rem; font-weight:600;
            line-height:1.4; margin:0 0 .9rem;
        }
        .paper-meta { display:flex; flex-wrap:wrap; gap:.45rem; }
        .paper-meta-chip {
            display:inline-flex; align-items:center; max-width:100%; padding:.35rem .65rem;
            border-radius:999px; background:#f1f3f4; color:var(--scholar-muted);
            font-size:.8rem; line-height:1.35;
        }
        .document-status {
            display:inline-flex; align-items:center; padding:.35rem .65rem;
            border-radius:999px; font-size:.8rem; font-weight:600;
        }
        .document-status::before { content:""; width:.42rem; height:.42rem; margin-right:.4rem; border-radius:50%; }
        .status-ready { background:#e6f4ea; color:#137333; }
        .status-ready::before { background:#34a853; }
        .status-missing { background:#f1f3f4; color:var(--scholar-muted); }
        .status-missing::before { background:#9aa0a6; }
        .abstract-panel {
            max-width:850px; padding:1.2rem 1.35rem; border:1px solid var(--scholar-border);
            border-radius:.65rem; background:#fff; color:#303134;
            font-size:1rem; line-height:1.8; white-space:pre-wrap;
        }
        [data-testid="stTabs"] { margin-top:1rem; }
        [data-testid="stTabs"] [role="tab"] { font-weight:600; padding:.65rem 1rem; }
        .empty-guide {
            padding:2.5rem 1rem; text-align:center; color:var(--scholar-muted);
            background:var(--scholar-surface); border-radius:.65rem;
        }
        div[data-baseweb="input"] > div, div[data-baseweb="select"] > div {
            border-color:var(--scholar-border);
        }
        div[data-baseweb="input"] > div:focus-within, div[data-baseweb="select"] > div:focus-within {
            border-color:var(--scholar-blue); box-shadow:0 0 0 1px var(--scholar-blue);
        }
        div[role="listbox"][aria-label^="보유 논문"],
        div[role="listbox"][aria-label^="번역 완료 논문"],
        div[role="listbox"][aria-label^="분석할 논문"] {
            max-height:12.5rem !important;
            overflow-y:auto !important;
        }
        [class*="st-key-document_reader_"] {
            max-width:900px; margin-top:.75rem;
        }
        [class*="st-key-document_reader_"] h1 {
            font-size:1.65rem !important; line-height:1.4 !important; margin:1rem 0 .8rem !important;
        }
        [class*="st-key-document_reader_"] h2 {
            font-size:1.35rem !important; line-height:1.45 !important; margin:1.8rem 0 .7rem !important;
        }
        [class*="st-key-document_reader_"] h3 {
            font-size:1.12rem !important; line-height:1.5 !important; margin:1.45rem 0 .55rem !important;
        }
        [class*="st-key-document_reader_"] h4 { font-size:1rem !important; margin-top:1.2rem !important; }
        [class*="st-key-document_reader_"] p,
        [class*="st-key-document_reader_"] li {
            color:#303134; font-size:1rem; line-height:1.78;
        }
        [class*="st-key-document_reader_"] blockquote {
            margin:1rem 0; padding:.75rem 1rem; border-left:4px solid #a8c7fa;
            background:#f8fafd; color:var(--scholar-muted);
        }
        [class*="st-key-document_reader_"] table { display:block; max-width:100%; overflow-x:auto; }
        [class*="st-key-document_reader_"] mjx-container { max-width:100%; overflow-x:auto; overflow-y:hidden; }
        [data-testid="stBaseButton-primary"], [data-testid="stBaseButton-primaryFormSubmit"] {
            background:var(--scholar-blue) !important; border-color:var(--scholar-blue) !important;
            color:#fff !important;
        }
        [data-testid="stBaseButton-primary"]:hover,
        [data-testid="stBaseButton-primaryFormSubmit"]:hover {
            background:var(--scholar-blue-dark) !important;
            border-color:var(--scholar-blue-dark) !important;
        }
        .stButton > button, .stFormSubmitButton > button { border-radius:.3rem; font-weight:500; }
        [data-testid="stSlider"] [role="slider"] { background:var(--scholar-blue) !important; }
        [data-testid="stChatMessage"] {
            max-width:900px; border:1px solid #e3e7ec; border-radius:.8rem;
            background:#fff; margin-bottom:.75rem; padding:.2rem .35rem;
            box-shadow:0 1px 2px rgba(60,64,67,.05);
        }
        [data-testid="stChatMessage"] p,
        [data-testid="stChatMessage"] li { font-size:1rem; line-height:1.72; }
        [data-testid="stChatMessage"]:has([data-testid="chatAvatarIcon-user"]) { background:#f5f9ff; }
        [class*="st-key-deep_search_controls"] {
            margin-bottom:1.25rem; background:#fbfcfe;
        }
        .control-button-label {
            min-height:1.55rem; color:var(--scholar-text); font-size:.875rem; margin-bottom:.25rem;
        }
        .selected-paper-note {
            display:inline-flex; max-width:100%; margin-top:.35rem; padding:.4rem .7rem;
            border-radius:.5rem; background:#e8f0fe; color:var(--scholar-blue-dark);
            font-size:.82rem; line-height:1.4;
        }
        .example-heading { margin:1.5rem 0 .65rem; font-size:.95rem; font-weight:700; }
        [class*="st-key-deep_search_example_"] button {
            min-height:3rem; border-color:#d7e3f4; background:#f8fafd;
            color:var(--scholar-blue-dark); font-weight:600;
        }
        [class*="st-key-deep_search_example_"] button:hover {
            border-color:#a8c7fa; background:#edf4ff; color:var(--scholar-blue-dark);
        }
        @media (max-width:700px) {
            .scholar-hero { padding-top:1.7rem; }
            .scholar-logo-image { height:150px; }
            .block-container { padding-top:1rem; }
            .paper-detail-card { padding:1rem; }
            .paper-detail-card h2 { font-size:1.15rem; }
            .abstract-panel { padding:1rem; font-size:.96rem; line-height:1.72; }
            [class*="st-key-document_reader_"] h1 { font-size:1.35rem !important; }
            [class*="st-key-document_reader_"] h2 { font-size:1.18rem !important; }
            [class*="st-key-document_reader_"] p,
            [class*="st-key-document_reader_"] li { font-size:.95rem; line-height:1.72; }
            [data-testid="stChatMessage"] p,
            [data-testid="stChatMessage"] li { font-size:.95rem; line-height:1.65; }
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def render_page_heading(title: str, description: str) -> None:
    """모든 화면에서 동일한 형식의 제목과 안내를 표시한다."""
    st.markdown(
        f"""
        <div class="page-heading">
            <h1>{escape(title)}</h1>
            <p>{escape(description)}</p>
        </div>
        """,
        unsafe_allow_html=True,
    )
