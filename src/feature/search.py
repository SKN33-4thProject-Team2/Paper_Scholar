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

# 로거 모듈 임포트 (기존 5000번대 공식 규격 반영)
try:
    from log.app_logger import AppLogger
    from log.log_codes import LogCode
except ImportError:
    class LogCode:
        PAPER_SEARCH_STARTED = 3100
        PAPER_SEARCH_SUCCEEDED = 3200
        PAPER_SEARCH_FAILED = 3500
        PAPER_SEARCH_REJECTED = 3400
        PAPER_SAVE_STARTED = 4100
        PAPER_SAVE_SUCCEEDED = 4200
        PAPER_SAVE_FAILED = 4500
        PAPER_SAVE_REJECTED = 4400
        PAPER_EXTRACTION_STARTED = 5100
        PAPER_EXTRACTION_SUCCEEDED = 5200
        PAPER_EXTRACTION_FAILED = 5500


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
    save_count: Optional[int] = Field(description="즉시 저장할 경우 저장할 논문 개수 (예: '5개 저장'이면 5, 미지정 시 None)", default=None)


class SaveActionIntent(BaseModel):
    action: str = Field(description="사용자의 의도. 'save'(저장/추가), 'cancel'(취소/해당없음/넘어가기) 중 하나", default="cancel")
    selected_numbers: List[int] = Field(description="저장할 논문의 번호 리스트", default_factory=list)


class KeywordConfirmIntent(BaseModel):
    action: str = Field(description="사용자의 의도. 'proceed', 'original', 'edit' 중 하나", default="proceed")


class ArxivSearchBot:
    """ArXiv 외부 논문 검색, 메타데이터 저장, 서재 조회/동기화, 본문 섹션 추출 및 벡터 색인을 전담하는 서비스 클래스"""

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

    def list_saved_papers(self) -> None:
        """내 서재(saved_papers.db)에 저장되어 있는 논문 목록과 본문 추출 상태를 출력한다."""
        if not os.path.exists(self.db_file):
            print("\n[System] 📭 아직 생성된 서재 DB가 없습니다.")
            return

        with sqlite3.connect(self.db_file) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT id, title, authors, created_at FROM papers ORDER BY created_at DESC")
            rows = cursor.fetchall()

        if not rows:
            print("\n[System] 📭 내 서재에 저장된 논문이 없습니다.")
            return

        extracted_pids = set()
        if os.path.exists(str(EXTRACTED_DB)):
            try:
                with sqlite3.connect(str(EXTRACTED_DB)) as ext_conn:
                    extracted_pids = {r[0] for r in
                                      ext_conn.execute("SELECT DISTINCT paper_id FROM paper_sections").fetchall()}
            except Exception:
                pass

        print(f"\n📚 [내 서재 보관 논문 목록 (총 {len(rows)}편)]")
        print("=" * 80)
        for idx, (pid, title, authors, created_at) in enumerate(rows, 1):
            status_tag = "✅ 본문/색인완료" if pid in extracted_pids else "⏳ 본문미추출"
            author_short = authors[:40] + "..." if authors and len(authors) > 40 else (authors or "저자 미상")
            print(f"[{idx:2d}] [{pid}] {title}")
            print(f"     └ 상태: {status_tag} | 저자: {author_short} | 저장일시: {created_at}")
            print("-" * 80)

    def sync_missing_papers(self) -> None:
        """서재 DB(saved_papers.db)와 추출 DB/Chroma의 차집합을 계산하여 미추출 논문을 일괄 추출·색인한다."""
        if not os.path.exists(self.db_file):
            print("\n[System] 📭 서재 DB가 존재하지 않습니다.")
            return

        with sqlite3.connect(self.db_file) as conn:
            saved_papers = conn.execute("SELECT id, title FROM papers").fetchall()

        if not saved_papers:
            print("\n[System] 📭 서재에 보관된 논문이 없습니다.")
            return

        extracted_pids = set()
        if os.path.exists(str(EXTRACTED_DB)):
            try:
                with sqlite3.connect(str(EXTRACTED_DB)) as ext_conn:
                    extracted_pids = {r[0] for r in
                                      ext_conn.execute("SELECT DISTINCT paper_id FROM paper_sections").fetchall()}
            except Exception:
                pass

        missing_extractions = [p for p in saved_papers if p[0] not in extracted_pids]

        print(f"\n🔄 [서재 본문 동기화 검사]")
        print(f"  - 총 보관 논문: {len(saved_papers)}편")
        print(f"  - 정상 추출 완료: {len(extracted_pids)}편")
        print(f"  - 본문 미추출/누락: {len(missing_extractions)}편")

        if missing_extractions:
            print(f"\n📥 총 {len(missing_extractions)}건의 미추출 논문 복구를 시작합니다...")
            for idx, (pid, title) in enumerate(missing_extractions, 1):
                print(f"  [{idx}/{len(missing_extractions)}] 🔄 [{pid}] 본문 추출 및 Chroma 색인 중...", end="", flush=True)
                try:
                    num_sec = extract_and_save(pid)
                    print(f" 완료 ({num_sec}개 섹션)")
                except Exception as e:
                    print(f" 실패 ({e})")
        else:
            print("  ✅ 모든 논문의 본문 섹션이 정상 적재되어 있습니다.")

        try:
            from services.fulltext_vector_store import ChromaFullTextStore
            store = ChromaFullTextStore()
            indexed_count = store.ensure_index()
            print(f"  ✅ Chroma 벡터 저장소 동기화 완료 (신규 반영 청크: {indexed_count}개)")
        except Exception as e:
            print(f"  ⚠️ Chroma 벡터 저장소 동기화 중 오류: {e}")

        print("\n🎉 모든 서재 데이터 동기화가 완료되었습니다.")

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
                    print(f"\n[Warning] ⚠️ arXiv 429 감지. {wait_time:.1f}초 대기 후 재시도... (시도 {attempt + 1}/{max_retries})")
                    time.sleep(wait_time)
                    if attempt == max_retries - 1:
                        self.logger.log(LogCode.PAPER_SEARCH_FAILED, query=final_query, error_type="RateLimit429",
                                        error=err_msg)
                        return []
                else:
                    self.logger.log(LogCode.PAPER_SEARCH_FAILED, query=final_query, error_type=type(e).__name__,
                                    error=err_msg)
                    return []

        self.logger.log(LogCode.PAPER_SEARCH_SUCCEEDED, query=final_query, result_count=len(results))
        return results

    def save_papers(self, selected_papers: List[dict], extract_content: bool = True) -> str:
        """선택된 논문을 저장하되, 이미 보관된 논문은 명시하고 건너뛰며 신규 논문만 추출·색인한다."""
        if not selected_papers:
            self.logger.log(LogCode.PAPER_SAVE_REJECTED, reason="empty_selection")
            return "저장할 논문이 없습니다."

        try:
            # Django/MySQL Paper 테이블 동기화
            # 기존 SQLite 기반 추출 파이프라인은 그대로 유지한다.
            mysql_created_count = 0
            mysql_updated_count = 0
            mysql_sync_error = None

            try:
                from services.django_paper_repository import upsert_papers

                mysql_created_count, mysql_updated_count = upsert_papers(
                    selected_papers
                )
                mysql_status_message = (
                    "[MySQL 동기화] "
                    f"신규 {mysql_created_count}건, "
                    f"갱신 {mysql_updated_count}건"
                )
                print(f"\n[System] ✅ {mysql_status_message}")

            except Exception as mysql_error:
                mysql_sync_error = str(mysql_error)
                mysql_status_message = (
                    "[MySQL 동기화 경고] "
                    "MySQL 저장에 실패하여 기존 SQLite 저장만 진행합니다."
                )
                print(f"\n[Warning] ⚠️ {mysql_status_message}")
                print(f"  - 원인: {mysql_sync_error}")

            # 1. 서재 DB에서 이미 저장된 paper_id 사전 조회
            with sqlite3.connect(self.db_file) as conn:
                cursor = conn.cursor()
                placeholders = ",".join(["?"] * len(selected_papers))
                target_ids = [p["id"] for p in selected_papers]
                cursor.execute(f"SELECT id FROM papers WHERE id IN ({placeholders})", target_ids)
                existing_ids = {row[0] for row in cursor.fetchall()}

            # 2. 신규 논문과 기등록 논문 분류
            new_papers = [p for p in selected_papers if p["id"] not in existing_ids]
            already_saved = [p for p in selected_papers if p["id"] in existing_ids]

            notice_lines = []
            if already_saved:
                print(f"\n[System] ℹ️ 이미 내 서재에 존재하는 논문 {len(already_saved)}건은 저장을 건너뜁니다:")
                for p in already_saved:
                    msg = f"  - [{p['id']}] {p['title']} (이미 보관 중)"
                    print(msg)
                    notice_lines.append(f"• [{p['id']}] 이미 서재에 존재함 (건너뜀)")

            if not new_papers:
                return (
                    f"{mysql_status_message}\n"
                    "선택하신 논문이 모두 이미 서재에 저장되어 있습니다.\n"
                    + "\n".join(notice_lines)
                )

            # 3. 신규 논문만 서재 DB(papers 테이블)에 INSERT
            self.logger.log(LogCode.PAPER_SAVE_STARTED, target_count=len(new_papers))
            with sqlite3.connect(self.db_file) as conn:
                cursor = conn.cursor()
                for paper in new_papers:
                    cursor.execute(
                        'INSERT INTO papers (id, title, authors, summary, pdf_url, created_at) VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)',
                        (paper['id'], paper['title'], paper['authors'], paper['summary'], paper['pdf_url'])
                    )
                cursor.execute(
                    'DELETE FROM papers WHERE id NOT IN (SELECT id FROM papers ORDER BY created_at DESC LIMIT 1000)')
                cursor.execute('SELECT id, title FROM papers ORDER BY created_at DESC')
                rows = cursor.fetchall()
                conn.commit()

            # JSON 인덱스 동기화
            json_data = {row[0]: {"id": row[0], "title": row[1]} for row in rows}
            with open(self.json_file, 'w', encoding='utf-8') as f:
                json.dump(json_data, f, ensure_ascii=False, indent=4)

            # 4. 신규 논문에 대해서만 본문 추출 및 Chroma 벡터 색인 실행
            extraction_results = []
            if extract_content:
                total_target = len(new_papers)
                print(f"\n[System] 📥 신규 논문 총 {total_target}건의 본문 추출 및 Chroma 벡터 색인을 시작합니다...")

                for idx, paper in enumerate(new_papers, 1):
                    pid = paper['id']
                    print(f"  [{idx}/{total_target}] 🔄 [{pid}] 본문 추출 및 벡터 색인 중...", end="", flush=True)

                    try:
                        start_time = time.time()
                        num_sections = extract_and_save(pid)
                        elapsed = round(time.time() - start_time, 2)

                        extraction_results.append(f"✓ [{pid}] {num_sections}개 섹션 추출 및 색인 완료 ({elapsed}s)")
                        print(f" 완료! ({num_sections}개 섹션, {elapsed}초)")

                    except Exception as ex:
                        extraction_results.append(f"✗ [{pid}] 추출/색인 실패: {ex}")
                        print(f" 실패! (이유: {ex})")

            final_message_parts = [
                mysql_status_message,
                (
                    f"신규 논문 {len(new_papers)}편이 서재에 추가되었습니다. "
                    f"(현재 총 서재 논문: {len(json_data)}편)"
                ),
            ]

            if notice_lines:
                final_message_parts.append(
                    "\n[기존 보관 논문 안내]\n"
                    + "\n".join(notice_lines)
                )

            if extraction_results:
                final_message_parts.append(
                    "\n[본문 추출 결과]\n"
                    + "\n".join(extraction_results)
                )

            self.logger.log(
                LogCode.PAPER_SAVE_SUCCEEDED,
                saved_count=len(new_papers),
                total_library_count=len(json_data),
                db_path=self.db_file,
                json_path=self.json_file,
                mysql_created_count=mysql_created_count,
                mysql_updated_count=mysql_updated_count,
                mysql_sync_error=mysql_sync_error,
            )

            return "\n".join(final_message_parts)

        except Exception as e:
            self.logger.log(
                LogCode.PAPER_SAVE_FAILED,
                target_count=len(selected_papers),
                error_type=type(e).__name__,
                error=str(e)
            )
            raise RuntimeError(f"논문 저장 중 오류가 발생했습니다: {e}") from e

    def start(self, initial_query: str = None) -> None:
        """대화형 터미널 CLI 루프 (서재 조회 / 동기화 / 단순 검색 / 즉시 원샷 저장 판별 지원)"""
        print("=" * 50)
        print(f"🤖 ArXiv 외부 검색 모드 시작 (Main Model: {self.model_name})")
        print("💡 팁: '서재 목록', '내 논문', '동기화'를 입력하면 보관된 논문 확인 및 복구가 가능합니다.")
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

            clean_input = user_input.strip()
            if not clean_input:
                continue
            if any(keyword in clean_input.lower() for keyword in ["종료", "그만", "중지", "멈춰", "q", "quit", "exit", "돌아가기"]):
                print("\n[System] 외부 검색을 종료합니다.")
                break

            # 1. 서재 목록 및 일괄 동기화 명령 감지
            no_space_input = re.sub(r"\s+", "", clean_input)
            if any(k in no_space_input for k in ["동기화", "서재동기화", "미추출추출", "전체추출", "복구"]):
                self.sync_missing_papers()
                continue

            if any(k in no_space_input for k in ["내서재", "서재목록", "내논문", "보관함", "저장된논문", "서재보여줘", "내논문목록"]):
                self.list_saved_papers()
                continue

            # 2. 사용자 검색/저장 의도 파싱
            params = self.parse_intent(clean_input)
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

            # 원샷 자동 저장 분기
            if auto_save:
                actual_save_count = save_count if save_count and 0 < save_count <= len(papers) else len(papers)
                target_papers = papers[:actual_save_count]
                print(f"\n[System] ⚡ 원샷 명령 감지: 상위 {actual_save_count}편을 즉시 서재 등록 및 본문 추출/색인합니다.")
                save_msg = self.save_papers(target_papers, extract_content=True)
                print(f"\n[System] 💾 {save_msg}")
            else:
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
    paper_ids: List[str] = Field(...,
                                 description="내 서재(Library DB)에 메타데이터를 저장하고, 본문 섹션 추출 및 벡터 색인까지 함께 수행할 논문 ID 목록 (예: ['2402.08954'])")


@tool("save_and_extract_papers", args_schema=SaveAndExtractToolInput)
def save_and_extract_papers_tool(paper_ids: List[str]) -> str:
    """선별된 논문의 메타데이터를 서재 DB에 등록하고, 본문 HTML 섹션을 추출 DB 및 Chroma 컬렉션에 영구 색인합니다."""
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
        return f"서재 저장 및 본문 추출/색인 실패: {str(e)}"


class SearchAgent:
    """자연어 지시를 해석하여 ArXiv 제목 검색, 서재 등록, 본문 섹션 추출 및 색인을 조율하는 에이전트"""

    def __init__(self, model_name: str = OPENAI_CHAT_MODEL):
        self.llm = create_safe_chat_model(model_name, temperature=0.0)
        self.tools = [
            search_arxiv_papers_tool,
            save_and_extract_papers_tool
        ]

        self.system_prompt = (
            "당신은 학술 논문 탐색 및 수집 전문 에이전트입니다.\n"
            "사용자의 요구사항에 따라 2개의 도구를 순차적으로 제어하세요:\n\n"
            "1. `search_arxiv_papers`: 사용자가 요청한 키워드와 개수에 맞춰 논문 제목(ti:)을 검색합니다.\n"
            "2. `save_and_extract_papers`: 검색 결과 중 사용자가 저장을 원하는 논문의 ID를 골라 서재 등록, 본문 섹션 추출 및 벡터 색인을 실행합니다.\n\n"
            "규칙:\n"
            "- 절대로 임의로 요약 리포트를 지어내지 말고, 수행된 작업 결과 목록을 명확히 출력하세요."
        )

        self.agent = create_react_agent(
            model=self.llm,
            tools=self.tools,
            prompt=self.system_prompt
        )

    def run(self, query: str) -> str:
        inputs = {"messages": [HumanMessage(content=query)]}
        response = self.agent.invoke(inputs)
        return response["messages"][-1].content


if __name__ == "__main__":
    bot = ArxivSearchBot()
    bot.start()
