# src/feature/search.py
import os
import sys
import time
import arxiv
import json
import sqlite3
from typing import List, Optional
from pathlib import Path
from dotenv import load_dotenv

from langchain_openai import ChatOpenAI
from pydantic import BaseModel, Field

# ---------------------------------------------------------------------
# [모듈 임포트 경로 설정: src 폴더 기준]
SRC_DIR = Path(__file__).resolve().parent.parent
if str(SRC_DIR) not in sys.path:
    sys.path.append(str(SRC_DIR))

from log.app_logger import AppLogger
from log.log_codes import LogCode
from tools.keyword_tool import generate_arxiv_keywords, KeywordToolError

# ---------------------------------------------------------------------

load_dotenv()
OPENAI_CHAT_MODEL = os.getenv("OPENAI_CHAT_MODEL", "gpt-5.6-luna")


class SearchIntent(BaseModel):
    query: Optional[str] = Field(description="사용자의 질문이나 요청에서 **순수한 핵심 검색어나 학술 주제(영어 명사형)**만 추출해주세요.", default=None)
    search_type: str = Field(description="제목 검색이면 't', 키워드/주제 검색이면 'k' (기본값 'k')", default="k")
    sort_by: str = Field(description="가장 유명한, 영향력 있는, 중요한 등의 뉘앙스가 있으면 'r'(영향력/관련도 순), 최신이면 'n'", default="r")
    max_results: int = Field(description="사용자가 요청한 논문의 개수 (명시되지 않았으면 10)", default=10)


class SaveActionIntent(BaseModel):
    action: str = Field(description="사용자의 의도. 'save'(저장/추가), 'cancel'(취소/해당없음/넘어가기) 중 하나", default="cancel")
    selected_numbers: List[int] = Field(description="저장할 논문의 번호 리스트", default_factory=list)


class KeywordConfirmIntent(BaseModel):
    action: str = Field(description="사용자의 의도. 'proceed', 'original', 'edit' 중 하나", default="proceed")


class ArxivSearchBot:
    """ArXiv 외부 논문 검색 및 메타데이터 저장을 담당하는 서비스 클래스"""

    def __init__(self, data_dir: Optional[str] = None, model_name: str = OPENAI_CHAT_MODEL):
        root_data_dir = Path(__file__).resolve().parent.parent.parent / "data" / "paper_list"
        self.data_dir = data_dir or str(root_data_dir)
        self.db_file = os.path.join(self.data_dir, "saved_papers.db")
        self.json_file = os.path.join(self.data_dir, "saved_papers.json")
        self.model_name = model_name
        self.llm = ChatOpenAI(model=self.model_name, temperature=0)

        self.logger = AppLogger(__name__)
        self.init_db()

    def init_db(self) -> None:
        """데이터베이스 및 저장 테이블을 생성한다."""
        try:
            os.makedirs(self.data_dir, exist_ok=True)
            conn = sqlite3.connect(self.db_file)
            cursor = conn.cursor()
            cursor.execute('''
                           CREATE TABLE IF NOT EXISTS papers
                           (
                               id         TEXT PRIMARY KEY,
                               title      TEXT,
                               authors    TEXT,
                               summary    TEXT,
                               pdf_url    TEXT,
                               created_at DATETIME DEFAULT CURRENT_TIMESTAMP
                           )
                           ''')
            cursor.execute("PRAGMA table_info(papers)")
            columns = [info[1] for info in cursor.fetchall()]
            if 'created_at' not in columns:
                cursor.execute("ALTER TABLE papers ADD COLUMN created_at DATETIME")
                cursor.execute("UPDATE papers SET created_at = CURRENT_TIMESTAMP")
            conn.commit()
            conn.close()
        except Exception as e:
            self.logger.log(
                LogCode.PAPER_SAVE_FAILED,
                stage="init_db",
                error_type=type(e).__name__,
                error=str(e)
            )

    def parse_intent(self, user_input: str) -> dict:
        structured_llm = self.llm.with_structured_output(SearchIntent)
        return structured_llm.invoke(f"다음 사용자의 요청에서 순수한 검색 파라미터를 추출해줘: {user_input}").model_dump()

    def parse_save_action(self, user_input: str, total_count: int) -> dict:
        structured_llm = self.llm.with_structured_output(SaveActionIntent)
        prompt = (f"다음 사용자의 응답에서 의도(save 또는 cancel)와 선택한 논문 번호를 추출해줘. 검색된 논문은 총 {total_count}개야. "
                  f"(만약 '전부', '다', '모두'라고 하면 1부터 {total_count}까지의 숫자를 리스트에 넣어줘)\n응답: {user_input}")
        try:
            return structured_llm.invoke(prompt).model_dump()
        except Exception:
            return {"action": "cancel", "selected_numbers": []}

    def parse_keyword_confirm(self, user_input: str) -> dict:
        if not user_input.strip():
            return {"action": "proceed"}
        try:
            return self.llm.with_structured_output(KeywordConfirmIntent).invoke(
                f"다음 사용자의 응답에서 키워드 검색 진행 옵션을 추출해줘.\n응답: {user_input}").model_dump()
        except Exception:
            return {"action": "proceed"}

    def search_papers(self, final_query: str, sort_by: str = 'r', max_results: int = 10) -> List[dict]:
        """ArXiv API를 호출하여 외부 논문을 검색하고 결과를 반환한다."""
        if not final_query or not final_query.strip():
            self.logger.log(
                LogCode.PAPER_SEARCH_REJECTED,
                reason="empty_query"
            )
            return []

        if not max_results or max_results > 15:
            max_results = 15

        sort_criterion = arxiv.SortCriterion.SubmittedDate if sort_by == 'n' else arxiv.SortCriterion.Relevance
        sort_name = "최신순" if sort_by == 'n' else "관련도(영향력)순"

        self.logger.log(
            LogCode.PAPER_SEARCH_STARTED,
            query=final_query,
            sort_by=sort_name,
            max_results=max_results
        )

        client = arxiv.Client(page_size=max_results, delay_seconds=3.0)
        search = arxiv.Search(
            query=final_query,
            max_results=max_results,
            sort_by=sort_criterion,
            sort_order=arxiv.SortOrder.Descending
        )

        results = []
        try:
            for paper in client.results(search):
                results.append({
                    "id": paper.get_short_id(),
                    "title": paper.title,
                    "authors": ", ".join([a.name for a in paper.authors]),
                    "summary": paper.summary.replace('\n', ' '),
                    "pdf_url": paper.pdf_url
                })

            self.logger.log(
                LogCode.PAPER_SEARCH_SUCCEEDED,
                query=final_query,
                result_count=len(results)
            )
        except Exception as e:
            self.logger.log(
                LogCode.PAPER_SEARCH_FAILED,
                query=final_query,
                error_type=type(e).__name__,
                error=str(e)
            )
            print(f"[Error] 검색 중 오류가 발생했습니다: {e}")

        return results

    def save_papers(self, selected_papers: List[dict]) -> str:
        """선택된 논문의 메타데이터를 SQLite DB 및 JSON 파일에 동시 저장한다."""
        if not selected_papers:
            self.logger.log(
                LogCode.PAPER_SAVE_REJECTED,
                reason="empty_selection"
            )
            return "저장할 논문이 없습니다."

        self.logger.log(
            LogCode.PAPER_SAVE_STARTED,
            target_count=len(selected_papers)
        )

        try:
            conn = sqlite3.connect(self.db_file)
            cursor = conn.cursor()
            for paper in selected_papers:
                try:
                    cursor.execute(
                        'INSERT OR IGNORE INTO papers (id, title, authors, summary, pdf_url, created_at) VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)',
                        (paper['id'], paper['title'], paper['authors'], paper['summary'], paper['pdf_url'])
                    )
                except Exception:
                    pass

            cursor.execute(
                'DELETE FROM papers WHERE id NOT IN (SELECT id FROM papers ORDER BY created_at DESC LIMIT 1000)')
            cursor.execute('SELECT id, title FROM papers ORDER BY created_at DESC')
            rows = cursor.fetchall()
            conn.commit()
            conn.close()

            json_data = {row[0]: {"id": row[0], "title": row[1]} for row in rows}
            with open(self.json_file, 'w', encoding='utf-8') as f:
                json.dump(json_data, f, ensure_ascii=False, indent=4)

            success_message = f"{len(selected_papers)}개의 논문이 내 서재에 추가되었습니다. (현재 총 논문 수: {len(json_data)}/1000개)"

            self.logger.log(
                LogCode.PAPER_SAVE_SUCCEEDED,
                saved_count=len(selected_papers),
                total_library_count=len(json_data),
                db_path=self.db_file,
                json_path=self.json_file
            )
            return success_message

        except Exception as e:
            self.logger.log(
                LogCode.PAPER_SAVE_FAILED,
                target_count=len(selected_papers),
                error_type=type(e).__name__,
                error=str(e)
            )
            raise RuntimeError(f"논문 저장 중 오류가 발생했습니다: {e}") from e

    def start(self, initial_query: str = None) -> None:
        """CLI 인터랙티브 실행 루프"""
        print("=" * 50)
        print(f"🤖 ArXiv 외부 검색 모드 시작 (Model: {self.model_name})")
        print("=" * 50)
        first_run = True

        while True:
            try:
                if first_run and initial_query:
                    user_input = initial_query
                    initial_query = None
                    first_run = False
                    print(f"\n[초기 검색어 자동 입력]: {user_input}")
                else:
                    user_input = input("\n[외부 검색] 무엇을 찾아드릴까요? (종료하려면 '그만' 입력): ")
            except KeyboardInterrupt:
                print("\n\n[System] 외부 검색 봇을 종료합니다.")
                break

            if not user_input.strip():
                continue
            if any(keyword in user_input.lower() for keyword in ["종료", "그만", "중지", "멈춰", "q", "quit", "exit", "돌아가기"]):
                print("\n[System] 외부 검색을 종료합니다.")
                break

            print("[System] LLM이 사용자 의도를 분석 중입니다...")
            params = self.parse_intent(user_input)
            if not params.get("query"):
                params["query"] = input("❓ 검색할 단어(영문)가 빠져있습니다. 무엇으로 검색할까요?: ")
            if not params.get("search_type"):
                params["search_type"] = 'k'
            if not params.get("sort_by"):
                params["sort_by"] = 'r'
            if not params.get("max_results"):
                params["max_results"] = 10

            final_query = None
            if params["search_type"] == 't':
                final_query = f'ti:"{params["query"]}"'
            else:
                while True:
                    try:
                        print(f"\n[Tool] 🧠 '{params['query']}'에 대한 학술 키워드를 생성 중입니다...")
                        keyword_result = generate_arxiv_keywords.invoke({"user_query": params["query"]})
                        expanded_keywords = keyword_result["keywords"]

                        print(f"\n[Human-in-the-Loop] 👀 파생 키워드:\n👉 {expanded_keywords}")
                        hitl_ans = input(
                            "[선택] 이 키워드들로 검색을 진행할까요?\n(예: '응 그걸로 해', '아니 원본 단어만 쓸래', '내가 직접 수정할게', 엔터(그대로 진행)): "
                        )
                        confirm_data = self.parse_keyword_confirm(hitl_ans)
                        action = confirm_data.get("action")

                        if action == "original":
                            final_keywords = [params["query"]]
                        elif action == "edit":
                            custom_kw = input("검색에 사용할 키워드를 쉼표(,)로 구분하여 직접 입력하세요: ")
                            final_keywords = [kw.strip() for kw in custom_kw.split(",") if kw.strip()]
                        else:
                            final_keywords = expanded_keywords

                        final_query = " OR ".join([f'all:"{kw}"' for kw in final_keywords])
                        break
                    except (KeywordToolError, Exception) as e:
                        print(f"\n[AI] 🤖 앗, 키워드 생성 중 문제가 발생했어요. (이유: {e})")
                        retry_ans = input("다시 시도(재검색) 해볼까요? (예/아니오): ").strip().lower()
                        if any(w in retry_ans for w in ["예", "응", "그래", "y", "yes"]):
                            continue
                        else:
                            final_query = None
                            break

            if not final_query:
                continue

            papers = self.search_papers(final_query, params["sort_by"], params["max_results"])
            if not papers:
                print("조건에 맞는 논문을 찾지 못했습니다.")
                continue

            print("\n[외부 검색 결과]")
            for idx, p in enumerate(papers):
                print(
                    f"{idx + 1}. [{p['id']}] {p['title']}\n   - 저자: {p['authors']}\n   - 요약: {p['summary']}\n" + "-" * 60
                )

            ans = input("\n[선택] 내 서재에 저장할 논문 번호를 말씀해주세요.\n(예: '1, 3번 저장해', '전부 다 저장해', 저장 안 하려면 엔터): ")
            if not ans.strip():
                continue

            action_data = self.parse_save_action(ans, len(papers))
            if action_data.get("action") == "save" and action_data.get("selected_numbers"):
                selected_indices = [num - 1 for num in action_data["selected_numbers"] if 0 < num <= len(papers)]
                if selected_indices:
                    save_msg = self.save_papers([papers[i] for i in selected_indices])
                    print(f"\n[System] 💾 {save_msg}")
                else:
                    print("\n[System] ⚠️ 올바른 번호가 인식되지 않아 저장이 취소되었습니다.")
            else:
                print("\n[System] 저장을 건너뜁니다.")


# ... (기존 search.py의 클래스 및 로직은 100% 그대로 유지) ...

# ---------------------------------------------------------------------
# [LangChain 에이전트 전용 툴 정의] (paper_extractor.py 처럼 맨 아래에 추가)
# ---------------------------------------------------------------------
from langchain_core.tools import tool


class ArxivToolInput(BaseModel):
    query: str = Field(..., description="ArXiv 논문 검색을 위한 영문 키워드")
    max_results: int = Field(default=5, description="검색할 최대 논문 수")


@tool("search_and_save_arxiv_papers", args_schema=ArxivToolInput)
def search_and_save_arxiv_papers(query: str, max_results: int = 5) -> str:
    """ArXiv에서 외부 논문을 검색하고 메타데이터를 로컬 서재에 자동 저장합니다."""
    # 사용자님이 만든 멀쩡한 봇을 그대로 가져와서 실행만 시켜줍니다.
    bot = ArxivSearchBot()
    papers = bot.search_papers(query, sort_by='r', max_results=max_results)

    if not papers:
        return f"'{query}'에 대한 외부 검색 결과가 없습니다."

    try:
        save_msg = bot.save_papers(papers)
        result_text = f"검색 및 저장 성공: {save_msg}\n"
        for p in papers:
            result_text += f"- [{p['id']}] {p['title']}\n"
        return result_text
    except Exception as e:
        return f"논문 저장 중 오류 발생: {e}"


# ---------------------------------------------------------------------
# [실행 메인 엔트리포인트]
# ---------------------------------------------------------------------
if __name__ == "__main__":
    bot = ArxivSearchBot()
    bot.start()
