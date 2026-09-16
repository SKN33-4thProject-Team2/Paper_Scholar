# src/feature/search.py
from __future__ import annotations

import os
import sys
import time
import json
import sqlite3
import random
import re
from typing import List, Dict, Optional
from pathlib import Path
from dotenv import load_dotenv

import arxiv
from langchain_openai import ChatOpenAI
from pydantic import BaseModel, Field
from langchain_core.tools import tool
from langchain_core.messages import HumanMessage
from langgraph.prebuilt import create_react_agent

# ---------------------------------------------------------------------
# [모듈 임포트 경로 설정: src 폴더 기준]
# ---------------------------------------------------------------------
SRC_DIR = Path(__file__).resolve().parent.parent
PROJECT_ROOT = SRC_DIR.parent
if str(SRC_DIR) not in sys.path:
    sys.path.append(str(SRC_DIR))
if str(PROJECT_ROOT) not in sys.path:
    sys.path.append(str(PROJECT_ROOT))

# 로거 모듈 임포트
try:
    from log.app_logger import AppLogger
    from log.log_codes import LogCode
except ImportError:
    class LogCode:
        PAPER_SEARCH_STARTED = "PAPER_SEARCH_STARTED"
        PAPER_SEARCH_SUCCEEDED = "PAPER_SEARCH_SUCCEEDED"
        PAPER_SEARCH_FAILED = "PAPER_SEARCH_FAILED"
        PAPER_SEARCH_REJECTED = "PAPER_SEARCH_REJECTED"
        PAPER_SAVE_STARTED = "PAPER_SAVE_STARTED"
        PAPER_SAVE_SUCCEEDED = "PAPER_SAVE_SUCCEEDED"
        PAPER_SAVE_FAILED = "PAPER_SAVE_FAILED"
        PAPER_SAVE_REJECTED = "PAPER_SAVE_REJECTED"

    class AppLogger:
        def __init__(self, name: str):
            self.name = name
        def log(self, code, **kwargs):
            pass

# 키워드 확장 툴 임포트
try:
    from tools.keyword_tool import generate_arxiv_keywords, KeywordToolError
except ImportError:
    generate_arxiv_keywords = None
    class KeywordToolError(Exception):
        pass

# tools 및 extractor_tool 모듈 임포트
try:
    from tools import EXTRACTED_DB, LIBRARY_DB
except ImportError:
    DATA_DIR = PROJECT_ROOT / "data"
    LIBRARY_DB = DATA_DIR / "paper_list" / "saved_papers.db"
    EXTRACTED_DB = DATA_DIR / "paper_extract" / "extracted_papers.db"

try:
    from tools.extractor_tool import extract_and_save, export_markdown, extract_paper_content_tool
except ImportError:
    try:
        from extractor_tool import extract_and_save, export_markdown, extract_paper_content_tool
    except ImportError:
        raise ImportError("extractor_tool.py 모듈을 찾을 수 없습니다. tools/extractor_tool.py 경로를 확인하세요.")

load_dotenv()
OPENAI_CHAT_MODEL = os.getenv("OPENAI_CHAT_MODEL", "gpt-5.6-luna")

# ---------------------------------------------------------------------
# [ArXiv API 전역 클라이언트: 최소 지연(0.5초)으로 즉각 반환]
# ---------------------------------------------------------------------
GLOBAL_ARXIV_CLIENT = arxiv.Client(
    page_size=15,
    delay_seconds=0.5,
    num_retries=3
)


def create_safe_chat_model(model_name: str, temperature: float = 0.0) -> ChatOpenAI:
    """추론(reasoning) 모델에서 Tool Calling 사용 시 400 에러를 방지하는 팩토리 함수"""
    try:
        return ChatOpenAI(
            model=model_name,
            temperature=temperature,
            reasoning_effort="none"
        )
    except (TypeError, ValueError):
        return ChatOpenAI(
            model=model_name,
            temperature=temperature,
            model_kwargs={"reasoning_effort": "none"}
        )


class SearchIntent(BaseModel):
    query: Optional[str] = Field(description="사용자의 질문이나 요청에서 **순수한 핵심 검색어나 학술 주제(영어 명사형)**만 추출해주세요.", default=None)
    search_type: str = Field(description="무조건 제목 검색 't'", default="t")
    sort_by: str = Field(description="가장 유명한, 영향력 있는, 중요한 등의 뉘앙스가 있으면 'r'(영향력/관련도 순), 최신이면 'n'", default="r")
    max_results: int = Field(description="사용자가 요청한 논문의 개수 (명시되지 않았으면 10)", default=10)
    auto_save: bool = Field(description="검색과 동시에 즉시 저장/다운로드를 요구했는지 여부 (예: '10개 찾고 5개 저장', '찾아서 바로 다운')", default=False)
    save_count: Optional[int] = Field(description="즉시 저장할 경우 저장할 논문 개수 (예: '5개 저장'이면 5, '전부 저장'이면 max_results와 동일, 미지정 시 None)", default=None)


class SaveActionIntent(BaseModel):
    action: str = Field(description="사용자의 의도. 'save'(저장/추가), 'cancel'(취소/해당없음/넘어가기) 중 하나", default="cancel")
    selected_numbers: List[int] = Field(description="저장할 논문의 번호 리스트", default_factory=list)


class KeywordConfirmIntent(BaseModel):
    action: str = Field(description="사용자의 의도. 'proceed', 'original', 'edit' 중 하나", default="proceed")


class ArxivSearchBot:
    """ArXiv 외부 논문 검색(원샷/순차 겸용), 메타데이터 저장, 본문 섹션 추출을 전담하는 서비스 클래스"""

    def __init__(self, data_dir: Optional[str] = None, model_name: str = OPENAI_CHAT_MODEL):
        root_data_dir = PROJECT_ROOT / "data" / "paper_list"
        self.data_dir = data_dir or str(root_data_dir)
        self.db_file = str(LIBRARY_DB) if LIBRARY_DB else os.path.join(self.data_dir, "saved_papers.db")
        self.json_file = os.path.join(self.data_dir, "saved_papers.json")
        self.model_name = model_name
        self.llm = create_safe_chat_model(self.model_name, temperature=0.0)

        self.logger = AppLogger(__name__)
        self.init_db()

    def init_db(self) -> None:
        """기존 스키마 규격을 준수하여 papers 테이블을 생성한다."""
        try:
            Path(self.db_file).parent.mkdir(parents=True, exist_ok=True)
            os.makedirs(self.data_dir, exist_ok=True)
            with sqlite3.connect(self.db_file) as conn:
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
        except Exception as e:
            self.logger.log(
                LogCode.PAPER_SAVE_FAILED,
                stage="init_db",
                error_type=type(e).__name__,
                error=str(e)
            )

    def parse_intent(self, user_input: str) -> dict:
        structured_llm = self.llm.with_structured_output(SearchIntent)
        return structured_llm.invoke(f"다음 사용자의 요청에서 검색 및 자동 저장 파라미터를 정확히 추출해줘: {user_input}").model_dump()

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
        """ArXiv API를 호출하여 제목(ti:) 기반으로 고속 검색하고 결과를 반환한다."""
        if not final_query or not final_query.strip():
            self.logger.log(LogCode.PAPER_SEARCH_REJECTED, reason="empty_query")
            return []

        max_results = min(max_results or 10, 15)
        sort_criterion = arxiv.SortCriterion.SubmittedDate if sort_by == 'n' else arxiv.SortCriterion.Relevance
        sort_name = "최신순" if sort_by == 'n' else "관련도(영향력)순"

        self.logger.log(
            LogCode.PAPER_SEARCH_STARTED,
            query=final_query,
            sort_by=sort_name,
            max_results=max_results
        )

        search = arxiv.Search(
            query=final_query,
            max_results=max_results,
            sort_by=sort_criterion,
            sort_order=arxiv.SortOrder.Descending
        )

        results = []
        max_retries = 3
        for attempt in range(max_retries):
            try:
                results.clear()
                for paper in GLOBAL_ARXIV_CLIENT.results(search):
                    clean_paper_id = re.sub(r"v\d+$", "", paper.get_short_id().strip())
                    results.append({
                        "id": clean_paper_id,
                        "title": paper.title,
                        "authors": ", ".join([a.name for a in paper.authors]),
                        "summary": paper.summary.replace('\n', ' '),
                        "pdf_url": paper.pdf_url
                    })
                break
            except Exception as e:
                err_msg = str(e)
                if "429" in err_msg or "Too Many Requests" in err_msg:
                    wait_time = (2 ** (attempt + 1)) * 1.5 + random.uniform(0.5, 1.5)
                    print(f"\n[Warning] ⚠️ arXiv 429 감지. {wait_time:.1f}초 대기 후 재시도... (시도 {attempt+1}/{max_retries})")
                    time.sleep(wait_time)
                    if attempt == max_retries - 1:
                        self.logger.log(LogCode.PAPER_SEARCH_FAILED, query=final_query, error_type="RateLimit429", error=err_msg)
                        return []
                else:
                    self.logger.log(LogCode.PAPER_SEARCH_FAILED, query=final_query, error_type=type(e).__name__, error=err_msg)
                    return []

        self.logger.log(LogCode.PAPER_SEARCH_SUCCEEDED, query=final_query, result_count=len(results))
        return results

    def save_papers(self, selected_papers: List[dict], extract_content: bool = True) -> str:
        """선택된 논문의 메타데이터 저장(LIBRARY_DB) 및 본문 섹션 추출(EXTRACTED_DB 적재)을 수행한다."""
        if not selected_papers:
            self.logger.log(LogCode.PAPER_SAVE_REJECTED, reason="empty_selection")
            return "저장할 논문이 없습니다."

        self.logger.log(LogCode.PAPER_SAVE_STARTED, target_count=len(selected_papers))

        try:
            # 1. 서재 DB (papers 테이블) 메타데이터 저장
            with sqlite3.connect(self.db_file) as conn:
                cursor = conn.cursor()
                for paper in selected_papers:
                    try:
                        cursor.execute(
                            'INSERT OR IGNORE INTO papers (id, title, authors, summary, pdf_url, created_at) VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)',
                            (paper['id'], paper['title'], paper['authors'], paper['summary'], paper['pdf_url'])
                        )
                    except Exception:
                        pass

                cursor.execute('DELETE FROM papers WHERE id NOT IN (SELECT id FROM papers ORDER BY created_at DESC LIMIT 1000)')
                cursor.execute('SELECT id, title FROM papers ORDER BY created_at DESC')
                rows = cursor.fetchall()
                conn.commit()

            # JSON 서재 인덱스 동기화
            json_data = {row[0]: {"id": row[0], "title": row[1]} for row in rows}
            with open(self.json_file, 'w', encoding='utf-8') as f:
                json.dump(json_data, f, ensure_ascii=False, indent=4)

            # 2. extractor_tool을 통한 본문 섹션 추출
            extraction_results = []
            if extract_content:
                total_target = len(selected_papers)
                print(f"\n[System] 📥 총 {total_target}건의 논문 본문 원본(HTML 섹션) 추출 작업을 시작합니다...")

                for idx, paper in enumerate(selected_papers, 1):
                    pid = paper['id']
                    print(f"  [{idx}/{total_target}] 🔄 [{pid}] 본문 추출 진행 중...", end="", flush=True)

                    try:
                        start_time = time.time()
                        num_sections = extract_and_save(pid)
                        elapsed = round(time.time() - start_time, 2)

                        extraction_results.append(f"✓ [{pid}] {num_sections}개 섹션 추출 완료 ({elapsed}s)")
                        print(f" 완료! ({num_sections}개 섹션, {elapsed}초)")

                    except Exception as ex:
                        extraction_results.append(f"✗ [{pid}] 본문 추출 실패: {ex}")
                        print(f" 실패! (이유: {ex})")

            success_message = (
                f"{len(selected_papers)}개의 논문이 내 서재에 추가되었습니다. (현재 총 서재 논문: {len(json_data)}개)\n"
                + "\n".join(extraction_results)
            )

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
        """대화형 터미널 CLI 루프 (단순 검색 / 즉시 원샷 저장 자동 판별 지원)"""
        print("=" * 50)
        print(f"🤖 ArXiv 외부 검색 모드 시작 (Main Model: {self.model_name})")
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

            # 1. 사용자 의도 고속 파싱 (단순 검색 vs 검색 후 즉시 저장 여부)
            params = self.parse_intent(user_input)
            if not params.get("query"):
                params["query"] = input("❓ 검색할 단어(영문)가 빠져있습니다. 무엇으로 검색할까요?: ")
            if not params.get("sort_by"):
                params["sort_by"] = 'r'
            if not params.get("max_results"):
                params["max_results"] = 10

            auto_save = params.get("auto_save", False)
            save_count = params.get("save_count")

            final_query = None
            if generate_arxiv_keywords is not None:
                # [자동화 분기] auto_save가 True인 경우 불필요한 사용자 확인(HITL)을 생략하고 바로 검색으로 직행
                if auto_save:
                    try:
                        print(f"\n[Tool] ⚡ '{params['query']}' 학술 키워드 생성 및 원스톱 파이프라인 가동...")
                        keyword_result = generate_arxiv_keywords.invoke({"user_query": params["query"]})
                        expanded_keywords = keyword_result["keywords"][:3]
                        sub_queries = [f'ti:"{kw}"' for kw in expanded_keywords]
                        final_query = " OR ".join(sub_queries)
                    except Exception:
                        final_query = f'ti:"{params["query"]}"'
                else:
                    # 단순 검색 시에는 키워드 검토 기회 제공
                    while True:
                        try:
                            kw_start = time.time()
                            print(f"\n[Tool] ⚡ '{params['query']}'에 대한 학술 키워드를 고속 생성 중입니다...")
                            keyword_result = generate_arxiv_keywords.invoke({"user_query": params["query"]})
                            expanded_keywords = keyword_result["keywords"]
                            print(f"[Tool 완료] 키워드 생성 소요 시간: {time.time() - kw_start:.2f}초")

                            print(f"\n[Human-in-the-Loop] 👀 파생 키워드:\n👉 {expanded_keywords}")
                            hitl_ans = input(
                                "[선택] 이 키워드들로 검색을 진행할까요?\n(예: 엔터(그대로 진행), '아니 원본 단어만 쓸래', '내가 직접 수정할게'): "
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

                            selected_kws = final_keywords[:3]
                            sub_queries = [f'ti:"{kw}"' for kw in selected_kws]
                            final_query = " OR ".join(sub_queries)
                            break

                        except (KeywordToolError, Exception) as e:
                            print(f"\n[AI] 🤖 키워드 생성 예외 발생: {e}")
                            final_query = f'ti:"{params["query"]}"'
                            break
            else:
                final_query = f'ti:"{params["query"]}"'

            if not final_query:
                continue

            print(f"\n[ArXiv 검색 시작] 제목 쿼리: {final_query} (최대 {params['max_results']}건)...")
            start_time = time.time()
            papers = self.search_papers(final_query, params["sort_by"], params["max_results"])
            elapsed = time.time() - start_time
            print(f"[검색 완료] 소요 시간: {elapsed:.2f}초")

            if not papers:
                print("조건에 맞는 논문을 찾지 못했습니다.")
                continue

            print("\n[외부 검색 결과]")
            for idx, p in enumerate(papers):
                print(
                    f"{idx + 1}. [{p['id']}] {p['title']}\n   - 저자: {p['authors']}\n   - 요약: {p['summary'][:150]}...\n" + "-" * 60
                )

            # ---------------------------------------------------------
            # [동적 분기 처리]: 즉시 원샷 저장 vs 대화형 수동 번호 선택
            # ---------------------------------------------------------
            if auto_save:
                # 사용자가 '10개 찾고 5개 저장'과 같이 명령한 경우: 질문 없이 즉시 자동 저장
                actual_save_count = save_count if save_count and 0 < save_count <= len(papers) else len(papers)
                target_papers = papers[:actual_save_count]
                print(f"\n[System] ⚡ 원샷 명령 감지: 상위 {actual_save_count}편을 즉시 서재 등록 및 본문 추출합니다.")
                save_msg = self.save_papers(target_papers, extract_content=True)
                print(f"\n[System] 💾 {save_msg}")
            else:
                # 단순 검색 요청인 경우: 번호를 선택받는 순차 대화 진행
                ans = input("\n[선택] 내 서재에 저장하고 본문을 추출할 논문 번호를 입력하세요.\n(예: '1, 3번 저장해', '전부 다 저장해', 저장 안 하려면 엔터): ")
                if not ans.strip():
                    continue

                action_data = self.parse_save_action(ans, len(papers))
                if action_data.get("action") == "save" and action_data.get("selected_numbers"):
                    selected_indices = [num - 1 for num in action_data["selected_numbers"] if 0 < num <= len(papers)]
                    if selected_indices:
                        save_msg = self.save_papers([papers[i] for i in selected_indices], extract_content=True)
                        print(f"\n[System] 💾 {save_msg}")
                    else:
                        print("\n[System] ⚠️ 올바른 번호가 인식되지 않아 저장이 취소되었습니다.")
                else:
                    print("\n[System] 저장을 건너뜁니다.")


# ---------------------------------------------------------------------
# [LangChain 에이전트 전용 Tool 정의]
# ---------------------------------------------------------------------
_SEARCH_CACHE: Dict[str, dict] = {}


class ArxivSearchToolInput(BaseModel):
    query: str = Field(..., description="ArXiv 논문 제목(title) 검색을 위한 영문 키워드")
    max_results: int = Field(default=10, description="검색할 최대 논문 수 (기본 10)")
    sort_by: str = Field(default="r", description="관련도순이면 'r', 최신순이면 'n'")


@tool("search_arxiv_papers", args_schema=ArxivSearchToolInput)
def search_arxiv_papers_tool(query: str, max_results: int = 10, sort_by: str = "r") -> str:
    """ArXiv API를 호출하여 논문 제목(ti:) 기준으로 메타데이터(ID, 제목, 저자, 초록)를 초고속 검색합니다."""
    global _SEARCH_CACHE
    bot = ArxivSearchBot()
    clean_query = query.strip().replace('"', '')
    optimized_query = f'ti:"{clean_query}"' if not clean_query.startswith("ti:") else clean_query
    papers = bot.search_papers(final_query=optimized_query, sort_by=sort_by, max_results=max_results)

    if not papers:
        return f"'{query}'에 대한 검색 결과가 없습니다."

    formatted = [f"총 {len(papers)}개의 논문이 검색되었습니다:"]
    for idx, p in enumerate(papers, 1):
        _SEARCH_CACHE[p["id"]] = p
        formatted.append(
            f"[{idx}] Paper ID: {p['id']}\n"
            f"    제목: {p['title']}\n"
            f"    저자: {p['authors']}\n"
            f"    초록 요약: {p['summary'][:180]}..."
        )
    return "\n\n".join(formatted)


class SaveAndExtractToolInput(BaseModel):
    paper_ids: List[str] = Field(..., description="내 서재(Library DB)에 메타데이터를 저장하고, 본문 섹션(Extracted DB)까지 함께 추출할 논문 ID 목록 (예: ['2402.08954', '2312.00752'])")


@tool("save_and_extract_papers", args_schema=SaveAndExtractToolInput)
def save_and_extract_papers_tool(paper_ids: List[str]) -> str:
    """선별된 논문의 메타데이터를 서재 DB(papers 테이블)에 등록하고,
    동시에 extractor_tool을 실행해 본문 HTML 섹션을 추출 DB(paper_sections 테이블)에 영구 적재합니다.
    """
    global _SEARCH_CACHE
    bot = ArxivSearchBot()

    selected_papers = []
    missing_ids = []

    for pid in paper_ids:
        clean_pid = re.sub(r"v\d+$", "", pid.strip())
        if clean_pid in _SEARCH_CACHE:
            selected_papers.append(_SEARCH_CACHE[clean_pid])
        else:
            missing_ids.append(clean_pid)

    if missing_ids:
        search = arxiv.Search(id_list=missing_ids)
        try:
            for result in GLOBAL_ARXIV_CLIENT.results(search):
                clean_pid = re.sub(r"v\d+$", "", result.get_short_id().strip())
                p_dict = {
                    "id": clean_pid,
                    "title": result.title,
                    "authors": ", ".join([a.name for a in result.authors]),
                    "summary": result.summary.replace("\n", " "),
                    "pdf_url": result.pdf_url
                }
                _SEARCH_CACHE[clean_pid] = p_dict
                selected_papers.append(p_dict)
        except Exception as e:
            print(f"[Warning] ID 보충 검색 중 예외 발생: {e}")

    if not selected_papers:
        return f"저장할 논문 데이터를 찾을 수 없습니다. (요청 ID: {paper_ids})"

    try:
        msg = bot.save_papers(selected_papers, extract_content=True)
        return msg
    except Exception as e:
        return f"서재 저장 및 본문 추출 실패: {str(e)}"


# ---------------------------------------------------------------------
# [SearchAgent: 검색-서재저장-본문추출 자율 오케스트레이션 에이전트]
# ---------------------------------------------------------------------
class SearchAgent:
    """자연어 지시를 해석하여 ArXiv 제목 검색, 서재 등록, 본문 섹션 추출을 조율하는 에이전트"""

    def __init__(self, model_name: str = OPENAI_CHAT_MODEL):
        self.llm = create_safe_chat_model(model_name, temperature=0.0)
        self.tools = [
            search_arxiv_papers_tool,
            save_and_extract_papers_tool
        ]

        self.system_prompt = (
            "당신은 학술 논문 탐색 및 수집 전문 에이전트입니다.\n"
            "사용자의 요구사항에 따라 2개의 도구를 순차적으로 제어하세요:\n\n"
            "1. `search_arxiv_papers`: 사용자가 요청한 키워드와 개수(예: 10개)에 맞춰 논문 제목(ti:)을 검색합니다.\n"
            "2. `save_and_extract_papers`: 검색 결과 중 사용자가 저장을 원하는 논문(예: '상위 5개', '전부' 등)의 ID를 골라 서재 등록 및 본문 섹션 추출을 실행합니다.\n\n"
            "규칙:\n"
            "- 절대로 임의로 요약 리포트를 지어내지 말고, 수행된 작업 결과(검색 목록, 서재 저장 및 본문 추출 성공 현황)를 명확한 목록 형태로 출력하세요."
        )

        self.agent = create_react_agent(
            model=self.llm,
            tools=self.tools,
            prompt=self.system_prompt
        )

    def run(self, query: str) -> str:
        """자연어 지시사항을 전달받아 에이전트 워크플로우를 실행"""
        inputs = {"messages": [HumanMessage(content=query)]}
        response = self.agent.invoke(inputs)
        return response["messages"][-1].content


# ---------------------------------------------------------------------
# [실행 엔트리포인트]
# ---------------------------------------------------------------------
if __name__ == "__main__":
    bot = ArxivSearchBot()
    bot.start()