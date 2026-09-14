"""Supervisor 그래프에 그대로 물어보는 대화 화면.

main.py 를 터미널에서 돌릴 때와 같은 흐름이다. 입력을 SupervisorChatbot 에
넘기고 돌아온 response 와 sources 를 그대로 보여 준다. 검색·번역·요약 중
무엇을 할지는 화면이 아니라 Supervisor 가 정한다.

thread_id 를 세션마다 하나씩 들고 있어 대화가 이어진다. 새로 시작하려면
사이드바가 아니라 화면 위의 '새 대화' 로 thread_id 를 갈아 끼운다.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from uuid import uuid4

import streamlit as st

from apps.ui import image_data_url, normalize_math


MESSAGES_KEY = "supervisor_messages"
THREAD_KEY = "supervisor_thread_id"
BOT_NAME = "PAPER BOT"
LOGO_PATH = Path(__file__).resolve().parent / "paper_scholar_logo.png"

# 사람이 오른쪽, 챗봇이 왼쪽에 앉는 메신저 배치. Streamlit 의 chat_message 는
# 둘 다 왼쪽에 세우므로 아바타 testid 로 사람 쪽만 골라 뒤집는다.
CHAT_STYLES = """
<style>
[data-testid="stChatMessage"] {
    display: flex;
    align-items: flex-start;
    /* row-reverse 인 사람 쪽은 오른쪽부터 쌓인다. */
    justify-content: flex-start;
    background: transparent;
    border: none;
    padding: 0.2rem 0;
    gap: 0.5rem;
}
[data-testid="stChatMessageContent"] {
    flex: 0 1 auto;
    width: auto;
    max-width: 40rem;
    margin: 0;
    background: #f1f3f4;
    border-radius: 1.1rem;
    padding: 0.7rem 1rem;
}
/* 사람 쪽만 오른쪽으로 넘긴다. */
[data-testid="stChatMessage"]:has([data-testid="stChatMessageAvatarUser"]) {
    flex-direction: row-reverse;
}
[data-testid="stChatMessage"]:has([data-testid="stChatMessageAvatarUser"])
[data-testid="stChatMessageContent"] {
    background: #1a73e8;
}
[data-testid="stChatMessage"]:has([data-testid="stChatMessageAvatarUser"])
[data-testid="stChatMessageContent"] p {
    color: #fff;
}
[data-testid="stChatMessageContent"] p:last-child { margin-bottom: 0; }
/* Streamlit 은 마크다운 상자에 margin-bottom:-16px 을 걸어 바깥 세로 간격을
   상쇄한다. 말풍선 안에는 그 간격이 없어서 글자가 아래로 5px 삐져나온다. */
[data-testid="stChatMessageContent"] [data-testid="stMarkdownContainer"] {
    margin-bottom: 0;
}
[data-testid="stChatMessageContent"] [data-testid="stVerticalBlock"] {
    gap: 0.35rem;
}
.chat-empty { text-align: center; padding: 2.6rem 1rem 1rem; }
.chat-empty-logo {
    display: block;
    width: min(420px, 80%);
    height: 150px;
    object-fit: cover;
    object-position: center;
    margin: 0 auto 1.3rem;
    border-radius: 1rem;
}
.chat-empty strong {
    display: block;
    font-size: 1.4rem;
    font-weight: 600;
    letter-spacing: -0.01em;
    color: var(--scholar-text);
}
.chat-empty p {
    color: var(--scholar-muted);
    margin: 0.6rem 0 2rem;
    line-height: 1.8;
    font-size: 0.95rem;
}
.chat-empty-label {
    color: var(--scholar-muted);
    font-size: 0.78rem;
    letter-spacing: 0.02em;
    margin-bottom: 0.6rem;
}
.chat-empty-hints {
    display: flex;
    flex-wrap: wrap;
    justify-content: center;
    gap: 0.5rem;
}
.chat-empty-hints span {
    color: var(--scholar-muted);
    font-size: 0.86rem;
    padding: 0.4rem 0.9rem;
    border: 1px solid var(--scholar-border);
    border-radius: 999px;
    background: #fff;
}
</style>
"""


@st.cache_resource(show_spinner=False)
def _chatbot():
    """그래프는 한 번만 세운다. 매번 build_graph 를 부르면 화면이 멈춘다."""
    from feature.supervisor_chatbot import SupervisorChatbot

    return SupervisorChatbot()


def _reset() -> None:
    st.session_state[MESSAGES_KEY] = []
    st.session_state[THREAD_KEY] = f"ui-{uuid4().hex[:8]}"


def _render_message(message: dict[str, Any]) -> None:
    with st.chat_message(message["role"]):
        st.markdown(normalize_math(message["content"]))
        for source in message.get("sources", []):
            label = source.get("label") or "S?"
            title = source.get("title") or source.get("paper_id") or ""
            st.caption(f"[{label}] {title}")


def render_chatbot_page() -> None:
    """대화 하나만 있는 화면. 위는 주고받은 말, 아래는 입력창."""
    if MESSAGES_KEY not in st.session_state:
        _reset()
    st.markdown(CHAT_STYLES, unsafe_allow_html=True)

    # 제목은 두지 않는다. 사이드바 탭에 이름이 이미 있고, 대화만 보이는 편이
    # 메신저에 가깝다. 오른쪽 위에 '새 대화' 만 남긴다.
    _, control = st.columns([5, 1])
    with control:
        if st.button("새 대화", use_container_width=True):
            _reset()
            st.rerun()

    # 입력을 먼저 읽는다. 나중에 읽으면 첫 질문을 보낸 순간에도 빈 화면 안내가
    # 함께 남는다. chat_input 은 호출 순서와 무관하게 맨 아래에 붙는다.
    question = st.chat_input("예: attention 관련된 논문 찾아줘")

    history = st.session_state[MESSAGES_KEY]
    if not history and not question:
        # 대화가 비면 가운데가 휑하다. 로고와 이름, 물어볼 예시로 채운다.
        logo_src = image_data_url(str(LOGO_PATH), LOGO_PATH.stat().st_mtime)
        st.markdown(
            f"""
            <div class="chat-empty">
                <img class="chat-empty-logo" src="{logo_src}" alt="{BOT_NAME}">
                <strong>{BOT_NAME}</strong>
                <p>
                    논문을 찾아 담고, 번역하고, 요약하고, 본문에 답하는 일을<br>
                    한 자리에서 이어서 합니다.
                </p>
                <div class="chat-empty-label">이렇게 물어보세요</div>
                <div class="chat-empty-hints">
                    <span>attention 관련된 논문 찾아줘</span>
                    <span>내 서재에 뭐가 있어?</span>
                    <span>1번 논문 요약해줘</span>
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )
    for message in history:
        _render_message(message)

    if not question:
        return

    user_message = {"role": "user", "content": question}
    history.append(user_message)
    _render_message(user_message)

    with st.chat_message("assistant"):
        with st.spinner("생각하는 중입니다..."):
            try:
                result = _chatbot().invoke(
                    question,
                    thread_id=st.session_state[THREAD_KEY],
                )
                answer = str(result.get("response") or "응답을 생성하지 못했습니다.")
                sources = list(result.get("sources") or [])
            except Exception as exc:
                answer, sources = f"요청을 처리하지 못했습니다: {exc}", []
        st.markdown(normalize_math(answer))
        for source in sources:
            label = source.get("label") or "S?"
            title = source.get("title") or source.get("paper_id") or ""
            st.caption(f"[{label}] {title}")

    history.append({"role": "assistant", "content": answer, "sources": sources})
