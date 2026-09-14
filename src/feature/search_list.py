# src/feature/search_list.py
import os
import sys
import json
import sqlite3
import requests
from typing import List, Optional
from pathlib import Path
from dotenv import load_dotenv

from langchain_openai import ChatOpenAI
from pydantic import BaseModel, Field

# ---------------------------------------------------------------------
# [모듈 임포트 경로 설정: 절대 경로 보정]
# ---------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
SRC_DIR = PROJECT_ROOT / "src"
for _path in (SRC_DIR, PROJECT_ROOT):
    if str(_path) not in sys.path:
        sys.path.append(str(_path))

DATA_LIST_DIR = PROJECT_ROOT / "data" / "paper_list"
PDF_SAVE_DIR = PROJECT_ROOT / "data" / "paper_save"

DB_FILE = DATA_LIST_DIR / "saved_papers.db"
JSON_FILE = DATA_LIST_DIR / "saved_papers.json"
DOWNLOADED_PDF_JSON = PDF_SAVE_DIR / "downloaded_pdfs.json"

load_dotenv()
OPENAI_CHAT_MODEL = "gpt-5.6-luna"
llm = ChatOpenAI(model=OPENAI_CHAT_MODEL, temperature=0)

# 동적 페이징을 위한 필드(list_count) 추가
class InitialIntent(BaseModel):
    intent: str = Field(description="'search'(검색), 'show_all'(전체보기), 'download_all'(전체 다운로드), 'exit'(종료) 중 하나",
                        default="search")
    search_keyword: str = Field(description="검색 키워드 또는 주제", default="")
    wants_download: bool = Field(description="검색이나 전체보기와 함께 곧바로 다운로드를 원하는지 여부", default=False)
    list_count: Optional[int] = Field(description="사용자가 한 번에 보여달라고 요구한 리스트의 개수 (예: 20개, 5개). 지정이 없으면 None", default=None)

def parse_initial_intent(user_input: str) -> dict:
    structured_llm = ChatOpenAI(model=OPENAI_CHAT_MODEL, temperature=0).with_structured_output(InitialIntent)
    prompt = (
        f"다음 사용자의 응답에서 의도를 분석해줘.\n"
        f"- 'intent': 'search'(특정 키워드 검색), 'show_all'(저장된 모든 리스트 보기), 'download_all'(현재 존재하는 모든 논문 다운), 'exit'(종료)\n"
        f"- 'search_keyword': 검색이나 관련 논문을 찾을 때의 핵심 키워드\n"
        f"- 'wants_download': 사용자가 당장 PDF 다운로드를 함께 원하면 True, 아니면 False\n"
        f"- 'list_count': 사용자가 구체적으로 몇 개를 보여달라고 숫자를 지정했으면 그 숫자를, 없으면 null\n"
        f"응답: {user_input}"
    )
    try:
        return structured_llm.invoke(prompt).model_dump()
    except Exception:
        return {"intent": "search", "search_keyword": user_input, "wants_download": False, "list_count": None}

class UserInteractionIntent(BaseModel):
    action: str = Field(
        description="'download'(PDF 다운로드), 'translate'(초록 번역), 'search'(새로운 검색/필터), 'page'(다음/이전 페이지 이동), 'cancel'(취소/종료) 중 하나",
        default="cancel")
    selected_numbers: List[int] = Field(description="대상 논문의 번호 리스트", default_factory=list)
    search_keyword: str = Field(description="새로 검색하고자 하는 키워드 또는 주제 (search 액션일 때 필수)", default="")
    page_direction: str = Field(description="페이지 이동 액션일 때 'next'(다음), 'prev'(이전)", default="")
    list_count: Optional[int] = Field(description="새로운 리스트 출력 시 요구된 개수 (예: '20개씩 보여줘')", default=None)

def parse_user_interaction(user_input: str, total_count: int) -> dict:
    structured_llm = ChatOpenAI(model=OPENAI_CHAT_MODEL, temperature=0).with_structured_output(UserInteractionIntent)
    prompt = (
        f"다음 응답에서 사용자의 의도를 분석해줘. 현재 보여진 논문은 총 {total_count}개야.\n"
        f"- 'download': PDF 다운로드 (예: '1번 다운', '모두 다')\n"
        f"- 'translate': 초록 번역 (예: '2번 요약 번역')\n"
        f"- 'search': 사용자가 현재 목록과 무관하게 새로운 주제나 키워드로 다시 찾아달라고 할 때\n"
        f"- 'page': 다음 페이지나 이전 페이지 리스트를 보고자 할 때 (예: '다음', '이전', '더 보여줘', '다음 20개')\n"
        f"- 'list_count': 사용자가 특정 갯수를 언급하면 그 숫자를 할당.\n"
        f"- 'cancel': 단순 엔터나 종료/뒤로가기\n"
        f"응답: {user_input}"
    )
    try:
        return structured_llm.invoke(prompt).model_dump()
    except Exception:
        return {"action": "cancel", "selected_numbers": [], "search_keyword": "", "page_direction": "", "list_count": None}

class LocalLibraryBot:
    def __init__(self):
        PDF_SAVE_DIR.mkdir(parents=True, exist_ok=True)
        DATA_LIST_DIR.mkdir(parents=True, exist_ok=True)

    def get_all_json_ids(self) -> List[str]:
        if not JSON_FILE.exists(): return []
        with open(JSON_FILE, 'r', encoding='utf-8') as f:
            try:
                return list(json.load(f).keys())
            except json.JSONDecodeError:
                return []

    def search_json(self, query: str) -> List[str]:
        if not JSON_FILE.exists(): return []
        with open(JSON_FILE, 'r', encoding='utf-8') as f:
            try:
                json_data = json.load(f)
            except json.JSONDecodeError:
                return []
        matched_ids = []
        keywords = query.lower().split()
        for pid, pdata in json_data.items():
            if all(kw in pdata.get("title", "").lower() for kw in keywords if len(kw) > 1):
                matched_ids.append(pid)
        return matched_ids

    def fetch_full_data_from_db(self, paper_ids: List[str]) -> List[dict]:
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        rows = []
        for i in range(0, len(paper_ids), 900):
            chunk = paper_ids[i:i + 900]
            cursor.execute(
                f"SELECT id, title, authors, summary, pdf_url FROM papers WHERE id IN ({','.join('?' for _ in chunk)})",
                chunk)
            rows.extend(cursor.fetchall())
        conn.close()
        row_dict = {r[0]: r for r in rows}
        return [{"id": r[0], "title": r[1], "authors": r[2], "summary": r[3], "pdf_url": r[4]} for pid in paper_ids if
                pid in row_dict for r in [row_dict[pid]]]

    def update_downloaded_pdf_json(self, paper_title: str, filepath: str):
        downloaded_data = {}
        if DOWNLOADED_PDF_JSON.exists():
            with open(DOWNLOADED_PDF_JSON, 'r', encoding='utf-8') as f:
                try:
                    downloaded_data = json.load(f)
                except json.JSONDecodeError:
                    pass
        downloaded_data[os.path.basename(filepath)] = {"title": paper_title, "filepath": str(filepath)}
        with open(DOWNLOADED_PDF_JSON, 'w', encoding='utf-8') as f:
            json.dump(downloaded_data, f, ensure_ascii=False, indent=4)

    def download_pdf(self, paper: dict) -> str:
        url = paper.get("pdf_url")
        if not url: return "no_url"
        pdf_url = url.replace("abs", "pdf") + ".pdf" if not url.endswith(".pdf") else url
        safe_title = "".join(c for c in paper['title'] if c.isalnum() or c in " _-").rstrip()
        filepath = PDF_SAVE_DIR / f"{safe_title[:60]}.pdf"

        if filepath.exists(): return "exists"
        print(f"\n[System] '{safe_title[:30]}...' 다운로드 중...")
        try:
            response = requests.get(pdf_url, stream=True, timeout=10)
            response.raise_for_status()
            with open(filepath, 'wb') as f:
                for chunk in response.iter_content(chunk_size=8192): f.write(chunk)
            print(f"다운로드 완료! 저장 위치: {filepath}")
            self.update_downloaded_pdf_json(paper['title'], str(filepath))
            return "success"
        except Exception as e:
            print(f"다운로드 실패: {e}")
            return "error"

    def process_downloads(self, papers: List[dict]):
        if not papers:
            print("\n[System] 다운로드할 논문이 없습니다.")
            return

        existing_papers, valid_to_download = [], []
        for idx, target in enumerate(papers):
            safe_title = "".join(c for c in target['title'] if c.isalnum() or c in " _-").rstrip()
            actual_num = target.get("_display_num", idx + 1)

            if (PDF_SAVE_DIR / f"{safe_title[:60]}.pdf").exists():
                existing_papers.append((actual_num, target))
            else:
                valid_to_download.append((actual_num, target))

        if existing_papers:
            exist_nums_str = ", ".join([str(p[0]) for p in existing_papers])
            print(f"\n[System] 대상 논문 중 {exist_nums_str}번은 이미 저장되어 있습니다.")

            if valid_to_download:
                valid_nums_str = ", ".join([str(p[0]) for p in valid_to_download])
                choice = input(f"이미 존재하는 파일을 제외하고 나머지({valid_nums_str}번)만 다운로드할까요? (예/아니오): ").strip().lower()
            else:
                choice = input("선택하신 모든 논문이 이미 존재합니다. 덮어쓰기하여 다시 다운로드 하시겠습니까? (예/아니오): ").strip().lower()

            if not any(w in choice for w in ["예", "응", "y", "yes", "네", "진행"]):
                print("[System] 기존 파일을 유지하며, 대상 파일들의 다운로드를 건너뜁니다.")
                if not valid_to_download:
                    return
            else:
                if not valid_to_download:
                    valid_to_download = existing_papers

        for num, paper in valid_to_download:
            if self.download_pdf(paper) == "exists":
                print(f" {num}번 '{paper['title'][:30]}...' 파일이 이미 존재하여 건너뜁니다.")

    def translate_summary(self, summary: str) -> str:
        try:
            return llm.invoke(f"다음 영문 논문 초록을 자연스럽고 전문적인 한국어로 번역해줘:\n\n{summary}").content
        except Exception as e:
            return f"번역 중 오류가 발생했습니다: {e}"

    def run(self):
        print("=" * 50)
        print(f"내 서재(Local JSON/DB) 관리 챗봇 (Model: {OPENAI_CHAT_MODEL})")
        print("=" * 50)

        matched_ids = []
        current_intent = "search"
        current_keyword = ""
        self.page_size = 10
        self.current_page = 1

        while True:
            if not matched_ids:
                try:
                    user_input = input(
                        "\n[내 서재] 무엇을 도와드릴까요?\n(예: '저장된 리스트 보여줘', 'Attention 논문 찾아줘', '현재 있는거 다 다운해줘'): ")
                except KeyboardInterrupt:
                    print("\n\n[System] 프로그램을 안전하게 종료합니다.")
                    break

                if not user_input.strip(): continue

                user_lower = user_input.lower()
                is_explicit_exit = any(k == user_lower.strip() for k in ["종료", "그만", "q", "quit", "exit"]) or any(
                    k in user_lower for k in ["종료해", "프로그램 종료", "그만", "중지", "멈춰", "q", "quit", "exit", "안해", "그만할래"])
                if is_explicit_exit and not any(w in user_lower for w in ["다운", "받", "저장", "번", "모두", "다", "찾아"]):
                    print("\n[System] 서재 챗봇을 종료합니다.")
                    break

                intent_data = parse_initial_intent(user_input)
                current_intent = intent_data.get("intent")
                current_keyword = intent_data.get("search_keyword", "")
                wants_download = intent_data.get("wants_download", False)
                requested_count = intent_data.get("list_count")

                if current_intent == "exit":
                    print("\n[System] 서재 챗봇을 종료합니다.")
                    break

                # 💡 동적 페이지 크기 조절: 기본 10개, 요구 개수 반영, 최대 99개 제한
                if requested_count is not None:
                    self.page_size = min(requested_count, 99)
                elif current_intent == "show_all":
                    self.page_size = 99
                else:
                    self.page_size = 10

                matched_ids = self.get_all_json_ids() if current_intent in ["show_all", "download_all"] else self.search_json(
                    current_keyword if current_keyword.strip() else user_input)

                if not matched_ids:
                    query_display = current_keyword if current_keyword.strip() else user_input
                    print(
                        f"\n[System] 내 서재에 '{query_display}'와(과) 일치하는 논문이 없습니다.\n안내: 외부 검색 봇('search.py')을 통해 먼저 검색/저장을 진행해 주세요.")
                    continue

                self.current_page = 1

                if wants_download or current_intent == "download_all":
                    print(f"\n[System] 조건에 맞는 총 {len(matched_ids)}개의 논문을 바로 다운로드합니다.")
                    papers_to_dl = self.fetch_full_data_from_db(matched_ids)
                    for idx, p in enumerate(papers_to_dl): p["_display_num"] = idx + 1
                    self.process_downloads(papers_to_dl)
                    matched_ids = []
                    continue

            total_count = len(matched_ids)
            total_pages = (total_count + self.page_size - 1) // self.page_size if self.page_size > 0 else 1
            if self.current_page > total_pages: self.current_page = total_pages
            if self.current_page < 1: self.current_page = 1

            start_idx = (self.current_page - 1) * self.page_size
            end_idx = min(start_idx + self.page_size, total_count)
            current_page_ids = matched_ids[start_idx:end_idx]

            current_papers = self.fetch_full_data_from_db(current_page_ids)

            print(
                f"\n[System] 총 {total_count}개의 논문 중 {start_idx + 1}~{end_idx}번째 논문입니다. (페이지 {self.current_page}/{total_pages})")
            print("-" * 60)
            for idx, p in enumerate(current_papers):
                display_num = start_idx + idx + 1
                if current_intent == "show_all" and not current_keyword.strip():
                    print(f"{display_num}. [{p['id']}] {p['title']}")
                else:
                    print(f"{display_num}. [{p['id']}] {p['title']}\n   - 저자: {p['authors']}\n   - 요약: {p['summary']}")
                print("-" * 60)

            try:
                ans = input(
                    "\n[선택]\n - PDF 다운로드 (예: '1번 다운', '모두 다운')\n - 초록 번역 (예: '2번 요약 번역')\n - 페이지 이동 (예: '다음', '이전', '20개씩 보여줘')\n - 새로운 주제 검색 (예: 'Attention 관련만 찾아줘')\n - 종료/뒤로가기 (엔터)\n> ")
            except KeyboardInterrupt:
                print("\n[System] 초기 화면으로 돌아갑니다.")
                matched_ids = []
                continue

            if not ans.strip():
                matched_ids = []
                continue

            action_data = parse_user_interaction(ans, total_count)
            action = action_data.get("action")
            requested_page_count = action_data.get("list_count")

            # 루프 도중에도 사용자가 개수 변경을 원하면 즉시 반영
            if requested_page_count is not None:
                self.page_size = min(requested_page_count, 99)

            if action == "page" or any(w in ans for w in ["다음", "이전", "더"]):
                direction = action_data.get("page_direction", "")
                if "이전" in ans or direction == "prev":
                    self.current_page = max(1, self.current_page - 1)
                else:
                    self.current_page = min(total_pages, self.current_page + 1)
                continue

            elif action == "search" or (
                    not action_data.get("selected_numbers") and action == "cancel" and len(ans.strip()) > 2):
                new_query = action_data.get("search_keyword") or ans.strip()
                print(f"\n[System] '{new_query}' 키워드로 서재 내에서 다시 검색합니다...")
                new_matched = self.search_json(new_query)
                if new_matched:
                    matched_ids = new_matched
                    self.current_page = 1
                    # 새 검색 시 사용자가 특정 개수를 요구하지 않았다면 기본값(10) 유지
                    if requested_page_count is None:
                        self.page_size = 10
                    current_intent = "search"
                    current_keyword = new_query
                else:
                    print(f"\n[System] '{new_query}'와(과) 일치하는 논문을 찾지 못했습니다. 기존 목록을 유지합니다.")
                continue

            elif action == "translate" and action_data.get("selected_numbers"):
                for num in action_data["selected_numbers"]:
                    if 1 <= num <= total_count:
                        p_data = self.fetch_full_data_from_db([matched_ids[num - 1]])
                        if p_data:
                            print(f"\n 번역 중...\n{self.translate_summary(p_data[0]['summary'])}\n{'=' * 60}")
                input("\n[안내] 번역을 확인하셨습니다. 엔터를 누르면 리스트로 돌아갑니다.")

            elif action == "download" and action_data.get("selected_numbers"):
                dl_papers = []
                for num in action_data["selected_numbers"]:
                    if 1 <= num <= total_count:
                        p_data = self.fetch_full_data_from_db([matched_ids[num - 1]])
                        if p_data:
                            p_data[0]["_display_num"] = num
                            dl_papers.append(p_data[0])
                if dl_papers:
                    self.process_downloads(dl_papers)
            else:
                print("\n[System] 초기 화면으로 돌아갑니다.")
                matched_ids = []

if __name__ == "__main__":
    LocalLibraryBot().run()