import os
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, HTTPException, Request, status
from pydantic import BaseModel

# FastAPI 앱 인스턴스 초기화
app = FastAPI(title="Paper Scholar LLM Serving")


# --- arXiv 검색 요청 데이터 모델 ---
class SearchRequest(BaseModel):
    query: Optional[str] = ""
    keyword: Optional[str] = ""
    sort_by: Optional[str] = "relevance"
    max_results: Optional[int] = 10


# --- LLM 추론 요청 데이터 모델 (백엔드 연동 규격) ---
class GenerateRequest(BaseModel):
    prompt: str
    max_tokens: Optional[int] = 1024


# --- [1] arXiv 검색 엔드포인트 ---
@app.post("/api/search")
@app.post("/api/search/")
async def search_arxiv(request: Request):
    try:
        payload = await request.json()
    except Exception:
        payload = {}

    # 프론트엔드 파라미터 매핑 (검색어 필드명 유연성 확보)
    search_query = payload.get("query") or payload.get("keyword") or payload.get("q") or ""
    max_results = payload.get("max_results") or payload.get("limit") or 10
    sort_by_input = payload.get("sort_by") or "relevance"

    # arXiv 정렬 기준 변환
    sort_map = {
        "relevance": "relevance",
        "관련도순": "relevance",
        "최신순": "submittedDate",
        "submittedDate": "submittedDate",
    }
    arxiv_sort_by = sort_map.get(sort_by_input, "relevance")

    if not search_query.strip():
        return {"papers": [], "results": [], "total": 0}

    # arXiv API 호출 및 XML 파싱
    encoded_query = urllib.parse.quote(search_query)
    api_url = (
        f"http://export.arxiv.org/api/query?search_query=all:{encoded_query}"
        f"&start=0&max_results={max_results}&sortBy={arxiv_sort_by}&sortOrder=descending"
    )

    try:
        req = urllib.request.Request(api_url, headers={"User-Agent": "PaperScholar/1.0"})
        with urllib.request.urlopen(req, timeout=10) as response:
            xml_data = response.read()

        root = ET.fromstring(xml_data)
        ns = {"atom": "http://www.w3.org/2005/Atom", "arxiv": "http://arxiv.org/schemas/atom"}

        results = []
        for entry in root.findall("atom:entry", ns):
            id_elem = entry.find("atom:id", ns)
            full_id = id_elem.text.strip() if id_elem is not None else ""
            arxiv_id = full_id.split("/abs/")[-1] if "/abs/" in full_id else full_id

            title_elem = entry.find("atom:title", ns)
            title = " ".join(title_elem.text.split()) if title_elem is not None else "No Title"

            summary_elem = entry.find("atom:summary", ns)
            summary = " ".join(summary_elem.text.split()) if summary_elem is not None else ""

            published_elem = entry.find("atom:published", ns)
            published = published_elem.text[:10] if published_elem is not None else ""

            authors = [
                author.find("atom:name", ns).text.strip()
                for author in entry.findall("atom:author", ns)
                if author.find("atom:name", ns) is not None
            ]

            pdf_url = f"https://arxiv.org/pdf/{arxiv_id}.pdf"

            paper_item = {
                "id": arxiv_id,
                "arxiv_id": arxiv_id,
                "title": title,
                "authors": authors,
                "abstract": summary,
                "summary": summary,
                "published": published,
                "published_date": published,
                "pdf_url": pdf_url,
                "url": full_id,
            }
            results.append(paper_item)

        # 프론트엔드 데이터 규격에 맞게 papers와 results 두 키를 모두 반환
        return {
            "status": "success",
            "papers": results,
            "results": results,
            "total": len(results),
        }
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"arXiv 검색 연동 실패: {str(e)}",
        )


# --- [2] RunPod LLM 모델 추론 엔드포인트 (요약 / 번역 / 질의응답) ---
@app.post("/generate")
@app.post("/generate/")
async def generate_text(request: GenerateRequest):
    """
    Django 백엔드의 요약, 번역, 질의응답 요청을 수신하여 텍스트를 반환하는 엔드포인트
    """
    try:
        # 실제 모델 파이프라인 호출 구문 (src 모듈이 있을 경우 연결)
        # 예: from src.services.llm_service import generate_response
        # response_text = generate_response(request.prompt, request.max_tokens)

        # 기본 응답 포맷
        response_text = f"[RunPod LLM Response] Processed prompt: {request.prompt[:100]}..."
        return {"text": response_text, "status": "success"}
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"LLM 추론 실패: {str(e)}",
        )


# --- [3] Uvicorn 서버 실행 블록 ---
if __name__ == "__main__":
    import uvicorn

    # 외부 터널 및 컨테이너 바인딩을 위해 0.0.0.0:8000으로 구동
    uvicorn.run(app, host="0.0.0.0", port=8000)