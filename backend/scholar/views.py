import logging
import os
import re
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
import requests

from django.contrib.auth import get_user_model
from django.db.models import Count, Exists, OuterRef
from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import generics, permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView

from scholar.jobs import enqueue_extraction_job
from scholar.models import Paper, PaperSection, LibraryEntry, PaperSummary, ProcessingJob, Translation
from scholar.serializers import (
    UserSerializer,
    RegisterSerializer,
    PaperListSerializer,
    PaperDetailSerializer,
    PaperSectionSerializer,
    PaperSummarySerializer,
    TranslationSerializer,
    ProcessingJobSerializer,
    ArxivSearchRequestSerializer,
    ArxivSearchResultSerializer,
    PaperSaveRequestSerializer,
    PaperSummarizeRequestSerializer,
    PaperTranslateRequestSerializer,
    PaperQuestionRequestSerializer,
)
from scholar.jobs import (
    enqueue_extraction_job,
    enqueue_summary_job,
    enqueue_translation_job,
)

User = get_user_model()
logger = logging.getLogger(__name__)


def save_papers_and_create_jobs(
    papers: list[dict],
    *,
    extract_content: bool,
    user,
) -> tuple[str, list[ProcessingJob]]:
    """검색 결과를 저장하고 사용자 서재 및 본문 추출 작업을 연결합니다."""
    from src.feature.search import ArxivSearchBot
    from src.services.django_paper_repository import normalize_arxiv_id

    legacy_papers = [
        {
            "id": normalize_arxiv_id(paper["arxiv_id"]),
            "title": paper["title"],
            "authors": ", ".join(paper["authors"]),
            "summary": paper["abstract"],
            "pdf_url": paper["pdf_url"],
        }
        for paper in papers
    ]
    save_message = ArxivSearchBot().save_papers(
        legacy_papers,
        extract_content=False,
    )

    saved_papers = []
    for paper_data in papers:
        paper = Paper.objects.get(
            arxiv_id=normalize_arxiv_id(paper_data["arxiv_id"])
        )
        LibraryEntry.objects.get_or_create(user=user, paper=paper)
        saved_papers.append(paper)

    if not extract_content:
        return save_message, []

    jobs = []
    for paper in saved_papers:
        if paper.sections.exists():
            job = paper.processing_jobs.filter(
                job_type=ProcessingJob.JobType.EXTRACT,
                status=ProcessingJob.Status.COMPLETED,
                user=user,
            ).first()
            if job is None:
                now = timezone.now()
                job = ProcessingJob.objects.create(
                    user=user,
                    paper=paper,
                    job_type=ProcessingJob.JobType.EXTRACT,
                    status=ProcessingJob.Status.COMPLETED,
                    progress_current=1,
                    progress_total=1,
                    started_at=now,
                    completed_at=now,
                )
        else:
            job = paper.processing_jobs.filter(
                job_type=ProcessingJob.JobType.EXTRACT,
                status__in=(
                    ProcessingJob.Status.PENDING,
                    ProcessingJob.Status.RUNNING,
                ),
            ).first()
            if job is None:
                job = ProcessingJob.objects.create(
                    user=user,
                    paper=paper,
                    job_type=ProcessingJob.JobType.EXTRACT,
                    status=ProcessingJob.Status.PENDING,
                    progress_total=1,
                )
                enqueue_extraction_job(job.id)
        jobs.append(job)

    return save_message, jobs


# --- [Fallback 엔진] RunPod 우선 호출 및 자동 우회 공통 함수 ---
def call_llm_with_fallback(prompt: str, max_tokens: int = 1024, fallback_type: str = "summary") -> tuple[str, str]:
    """
    1차: RunPod LLM 인스턴스 호출 (타임아웃 5초)
    2차: RunPod 응답 실패/미가동 시 OpenAI API 자동 우회
    3차: API 키 부재 또는 외부망 단절 시 안정적인 안내 텍스트 반환 (500 방지)

    Returns:
        (생성된_텍스트, 사용된_모델명)
    """
    runpod_url = os.getenv("RUNPOD_API_URL", "https://llm.skn33-project.store").rstrip("/")
    openai_key = os.getenv("OPENAI_API_KEY", "").strip()

    # 1. RunPod 1차 시도 (빠른 판단을 위해 5초 타임아웃)
    try:
        res = requests.post(
            f"{runpod_url}/generate",
            json={"prompt": prompt, "max_tokens": max_tokens},
            timeout=5
        )
        if res.status_code == 200:
            result_text = res.json().get("text", res.text).strip()
            if result_text:
                return result_text, "runpod-llm"
        logger.warning(f"[LLM Routing] RunPod 응답 비정상 (Status: {res.status_code}). Fallback으로 전환합니다.")
    except Exception as e:
        logger.warning(f"[LLM Routing] RunPod 통신 불가 ({str(e)}). Fallback으로 전환합니다.")

    # 2. OpenAI API 2차 우회 (OPENAI_API_KEY 존재 시)
    if openai_key:
        try:
            import openai
            client = openai.OpenAI(api_key=openai_key)
            completion = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[{"role": "user", "content": prompt}],
                max_tokens=max_tokens,
                timeout=10
            )
            return completion.choices[0].message.content.strip(), "openai-gpt-4o-mini-fallback"
        except Exception as fallback_err:
            logger.error(f"[LLM Routing] OpenAI Fallback 호출 실패: {fallback_err}")

    # 3. 모든 외부 연동 실패 시 기본 안전 문구 (500 에러 차단)
    fallback_messages = {
        "summary": "현재 전용 GPU 서버가 절전 대기 모드입니다. 잠시 후 다시 시도해 주시거나 본문 초록을 직접 확인해 주세요.",
        "translation": "현재 번역 엔진 인스턴스가 연결 대기 중입니다. 잠시 후 다시 요청해 주세요.",
        "question": "현재 GPU 질의응답 인스턴스가 유휴 상태입니다. 잠시 후 다시 질문해 주세요."
    }
    return fallback_messages.get(fallback_type, "요청을 처리할 수 없습니다. 잠시 후 다시 시도해 주세요."), "system-standby"


def health_check(request):
    """
    서버 헬스 체크
    """
    return JsonResponse({"status": "ok", "service": "Paper Scholar Backend"})


class RegisterAPIView(APIView):
    """
    회원가입 API
    """
    permission_classes = [permissions.AllowAny]

    def post(self, request, *args, **kwargs):
        serializer = RegisterSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.save()
        return Response(
            {
                "status": "success",
                "message": "User registered successfully",
                "user": UserSerializer(user).data,
            },
            status=status.HTTP_201_CREATED,
        )


class CurrentUserAPIView(APIView):
    """
    현재 로그인된 사용자 정보 조회
    """
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, *args, **kwargs):
        serializer = UserSerializer(request.user)
        return Response(serializer.data, status=status.HTTP_200_OK)


def paper_api_queryset(user=None):
    """
    Paper 목록/상세 공통 쿼리셋 (summary_records 에러 차단 및 역참조 최적화)
    """
    queryset = (
        Paper.objects.prefetch_related(
            "sections",
            "translations",
            "library_entries",
        )
        .annotate(
            api_section_count=Count("sections", distinct=True),
            api_translation_count=Count("translations", distinct=True),
            api_has_summary=Exists(
                PaperSummary.objects.filter(paper_id=OuterRef("pk"))
            ),
        )
        .order_by("-published_at", "-created_at")
    )
    if user is not None and getattr(user, "is_authenticated", False):
        queryset = queryset.filter(library_entries__user=user)
    return queryset


class ArxivSearchAPIView(APIView):
    """
    Arxiv 논문 검색 API
    """
    permission_classes = [permissions.AllowAny]

    def post(self, request, *args, **kwargs):
        serializer = ArxivSearchRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        query = serializer.validated_data["query"]
        max_results = serializer.validated_data.get("max_results", 10)

        # 1. 쿼리 파라미터 정제 및 URL 인코딩
        clean_query = query.strip()
        encoded_query = urllib.parse.quote(clean_query)
        search_url = (
            "https://export.arxiv.org/api/query"
            f"?search_query=all:{encoded_query}&start=0&max_results={max_results}"
        )

        # arXiv 는 기본 Python User-Agent 를 406 으로 거부한다.
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36 PaperScholar/1.0"
            )
        }

        def empty(message: str, error: str = "") -> Response:
            """실패해도 프론트가 읽는 키를 모두 채워 200 으로 돌려준다."""
            payload = {
                "status": "error" if error else "success",
                "query": clean_query,
                "count": 0,
                "total": 0,
                "papers": [],
                "results": [],
                "message": message,
            }
            if error:
                payload["error"] = error
            return Response(payload, status=status.HTTP_200_OK)

        try:
            # arXiv 가 느릴 때 몇 분까지 걸리는 경우가 있어 넉넉히 기다린다.
            resp = requests.get(search_url, headers=headers, timeout=30)

            if resp.status_code != 200:
                logger.warning(f"arXiv API 응답 비정상 (Status: {resp.status_code})")
                return empty("검색 결과가 없거나 외부 통신이 원활하지 않습니다.")

            root = ET.fromstring(resp.content)
            ns = {"atom": "http://www.w3.org/2005/Atom"}

            results = []
            for entry in root.findall("atom:entry", ns):
                raw_id_elem = entry.find("atom:id", ns)
                raw_id = raw_id_elem.text.strip() if raw_id_elem is not None else ""
                versioned_arxiv_id = (
                    raw_id.split("/abs/")[-1]
                    if "/abs/" in raw_id
                    else raw_id
                )
                arxiv_id = re.sub(r"v\d+$", "", versioned_arxiv_id)

                title_elem = entry.find("atom:title", ns)
                title = " ".join(title_elem.text.split()) if title_elem is not None else "No Title"

                summary_elem = entry.find("atom:summary", ns)
                abstract = " ".join(summary_elem.text.split()) if summary_elem is not None else ""

                authors = [
                    author.find("atom:name", ns).text.strip()
                    for author in entry.findall("atom:author", ns)
                    if author.find("atom:name", ns) is not None
                ]

                pdf_url = ""
                for link in entry.findall("atom:link", ns):
                    if link.attrib.get("title") == "pdf":
                        pdf_url = link.attrib.get("href")
                        break

                results.append(
                    {
                        "id": arxiv_id,
                        "arxiv_id": arxiv_id,
                        "title": title,
                        "authors": authors,
                        "abstract": abstract,
                        "summary": abstract,
                        "pdf_url": pdf_url,
                        "url": raw_id,
                    }
                )

            # 프론트는 query·count·results 를 읽는다. papers·total 은 호환용으로 함께 둔다.
            return Response(
                {
                    "status": "success",
                    "query": clean_query,
                    "count": len(results),
                    "total": len(results),
                    "papers": results,
                    "results": results,
                },
                status=status.HTTP_200_OK,
            )

        except Exception as e:
            logger.error(f"Arxiv search error: {e}")
            # 실패해도 200 을 주어 프론트의 results.length 가 터지지 않게 한다.
            return empty("검색 중 오류가 발생했습니다.", error=str(e))


class PaperListAPIView(generics.ListCreateAPIView):
    """
    논문 목록 및 수동 등록 API
    """
    serializer_class = PaperListSerializer
    permission_classes = [permissions.IsAuthenticatedOrReadOnly]

    def get_queryset(self):
        user = self.request.user if self.request.user.is_authenticated else None
        return paper_api_queryset(user)

    def perform_create(self, serializer):
        paper = serializer.save()
        if self.request.user.is_authenticated:
            LibraryEntry.objects.get_or_create(user=self.request.user, paper=paper)


class PaperDetailAPIView(generics.RetrieveUpdateDestroyAPIView):
    """
    논문 상세 정보 조회/수정/삭제
    """
    serializer_class = PaperDetailSerializer
    permission_classes = [permissions.IsAuthenticatedOrReadOnly]
    lookup_field = "arxiv_id"

    def get_queryset(self):
        user = self.request.user if self.request.user.is_authenticated else None
        return paper_api_queryset(user)


class PaperSaveAPIView(APIView):
    """검색한 논문을 내 서재에 저장하고, 요청하면 본문 추출 작업까지 건다."""

    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, *args, **kwargs):
        request_serializer = PaperSaveRequestSerializer(data=request.data)
        request_serializer.is_valid(raise_exception=True)
        params = request_serializer.validated_data

        try:
            save_message, jobs = save_papers_and_create_jobs(
                params["papers"],
                extract_content=params["extract_content"],
                user=request.user,
            )
        except Exception as exc:
            return Response(
                {"detail": f"논문 저장 중 오류가 발생했습니다: {exc}"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        return Response(
            {
                "message": save_message,
                "jobs": ProcessingJobSerializer(jobs, many=True).data,
            },
            status=(
                status.HTTP_202_ACCEPTED
                if jobs
                else status.HTTP_200_OK
            ),
        )


class PaperSectionsAPIView(generics.ListAPIView):
    """
    특정 논문의 섹션 본문 목록 조회
    """
    serializer_class = PaperSectionSerializer
    permission_classes = [permissions.IsAuthenticatedOrReadOnly]
    # 프론트는 이 응답을 배열 그대로 받아 map() 을 돌린다.
    # 전역 페이지네이션이 {count, results} 로 감싸면 화면이 터지므로 여기서만 끈다.
    pagination_class = None

    def get_queryset(self):
        arxiv_id = self.kwargs.get("arxiv_id")
        return PaperSection.objects.filter(paper__arxiv_id=arxiv_id).order_by("section_order")


class PaperExtractAPIView(APIView):
    """본문이 없거나 이전 추출이 실패한 서재 논문의 추출 작업을 등록합니다."""

    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, *args, **kwargs):
        paper = get_object_or_404(
            Paper,
            arxiv_id=self.kwargs["arxiv_id"],
            library_entries__user=request.user,
        )
        active_job = paper.processing_jobs.filter(
            job_type=ProcessingJob.JobType.EXTRACT,
            status__in=(
                ProcessingJob.Status.PENDING,
                ProcessingJob.Status.RUNNING,
            ),
        ).first()
        if active_job is not None:
            return Response(
                {"job": ProcessingJobSerializer(active_job).data},
                status=status.HTTP_202_ACCEPTED,
            )

        if paper.sections.exists():
            completed_job = paper.processing_jobs.filter(
                job_type=ProcessingJob.JobType.EXTRACT,
                status=ProcessingJob.Status.COMPLETED,
            ).first()
            if completed_job is None:
                now = timezone.now()
                completed_job = ProcessingJob.objects.create(
                    user=request.user,
                    paper=paper,
                    job_type=ProcessingJob.JobType.EXTRACT,
                    status=ProcessingJob.Status.COMPLETED,
                    progress_current=1,
                    progress_total=1,
                    started_at=now,
                    completed_at=now,
                )
            return Response(
                {"job": ProcessingJobSerializer(completed_job).data},
                status=status.HTTP_200_OK,
            )

        job = ProcessingJob.objects.create(
            user=request.user,
            paper=paper,
            job_type=ProcessingJob.JobType.EXTRACT,
            status=ProcessingJob.Status.PENDING,
            progress_total=1,
        )
        enqueue_extraction_job(job.id)
        return Response(
            {"job": ProcessingJobSerializer(job).data},
            status=status.HTTP_202_ACCEPTED,
        )


class PaperSummaryAPIView(generics.RetrieveAPIView):
    """
    논문 요약 결과 단일 조회
    """
    serializer_class = PaperSummarySerializer
    permission_classes = [permissions.IsAuthenticatedOrReadOnly]

    def get_object(self):
        arxiv_id = self.kwargs.get("arxiv_id")
        return get_object_or_404(PaperSummary, paper__arxiv_id=arxiv_id)


class PaperSummarizeAPIView(APIView):
    """저장된 본문을 이용하는 비동기 요약 작업을 등록합니다."""
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, arxiv_id, *args, **kwargs):
        serializer = PaperSummarizeRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        force = serializer.validated_data["force"]
        paper = get_object_or_404(
            Paper,
            arxiv_id=arxiv_id,
            library_entries__user=request.user,
        )

        if not paper.sections.exists():
            return Response(
                {"detail": "요약할 본문 섹션이 없습니다. 먼저 본문을 추출해 주세요."},
                status=status.HTTP_409_CONFLICT,
            )

        active_job = paper.processing_jobs.filter(
            job_type=ProcessingJob.JobType.SUMMARIZE,
            status__in=(ProcessingJob.Status.PENDING, ProcessingJob.Status.RUNNING),
        ).first()
        if active_job is not None:
            return Response(
                {
                    "message": "이미 요약 작업이 진행 중입니다.",
                    "job": ProcessingJobSerializer(active_job).data,
                },
                status=status.HTTP_202_ACCEPTED,
            )

        existing_summary = PaperSummary.objects.filter(paper=paper).first()
        if existing_summary is not None and not force:
            completed_job = paper.processing_jobs.filter(
                user=request.user,
                job_type=ProcessingJob.JobType.SUMMARIZE,
                status=ProcessingJob.Status.COMPLETED,
            ).first()
            if completed_job is None:
                now = timezone.now()
                completed_job = ProcessingJob.objects.create(
                    user=request.user,
                    paper=paper,
                    job_type=ProcessingJob.JobType.SUMMARIZE,
                    status=ProcessingJob.Status.COMPLETED,
                    progress_current=1,
                    progress_total=1,
                    model_name=existing_summary.model_name,
                    started_at=now,
                    completed_at=now,
                )
            return Response(
                {
                    "message": "이미 생성된 요약이 있습니다.",
                    "job": ProcessingJobSerializer(completed_job).data,
                }
            )

        job = ProcessingJob.objects.create(
            user=request.user,
            paper=paper,
            job_type=ProcessingJob.JobType.SUMMARIZE,
            status=ProcessingJob.Status.PENDING,
            progress_total=1,
        )
        enqueue_summary_job(job.id)
        return Response(
            {
                "message": "요약 작업을 시작했습니다.",
                "job": ProcessingJobSerializer(job).data,
            },
            status=status.HTTP_202_ACCEPTED,
        )


class PaperTranslationsAPIView(generics.ListAPIView):
    """
    특정 논문의 번역 목록 조회
    """
    serializer_class = TranslationSerializer
    permission_classes = [permissions.IsAuthenticated]
    # 프론트는 이 응답을 배열 그대로 받아 map() 을 돌린다.
    # 전역 페이지네이션이 {count, results} 로 감싸면 화면이 터지므로 여기서만 끈다.
    pagination_class = None

    def get_queryset(self):
        paper = get_object_or_404(
            Paper,
            arxiv_id=self.kwargs["arxiv_id"],
            library_entries__user=self.request.user,
        )
        queryset = paper.translations.select_related("paper")
        translation_type = self.request.query_params.get("type")
        if translation_type:
            queryset = queryset.filter(translation_type=translation_type)
        target_language = self.request.query_params.get("target_language")
        if target_language:
            queryset = queryset.filter(target_language=target_language)
        return queryset


class PaperTranslateAPIView(APIView):
    """최종 논문 요약을 번역하는 비동기 작업을 등록합니다."""
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, arxiv_id, *args, **kwargs):
        serializer = PaperTranslateRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        params = serializer.validated_data
        paper = get_object_or_404(
            Paper,
            arxiv_id=arxiv_id,
            library_entries__user=request.user,
        )

        if not PaperSummary.objects.filter(paper=paper).exists():
            return Response(
                {"detail": "번역할 요약이 없습니다. 먼저 요약을 생성해 주세요."},
                status=status.HTTP_409_CONFLICT,
            )

        active_job = paper.processing_jobs.filter(
            job_type=ProcessingJob.JobType.TRANSLATE,
            status__in=(ProcessingJob.Status.PENDING, ProcessingJob.Status.RUNNING),
        ).first()
        if active_job is not None:
            return Response(
                {
                    "message": "이미 번역 작업이 진행 중입니다.",
                    "job": ProcessingJobSerializer(active_job).data,
                },
                status=status.HTTP_202_ACCEPTED,
            )

        existing_translation = Translation.objects.filter(
            paper=paper,
            translation_type=Translation.TranslationType.SUMMARY,
            target_language=params["target_language"],
        ).first()
        if existing_translation is not None and not params["force"]:
            completed_job = paper.processing_jobs.filter(
                user=request.user,
                job_type=ProcessingJob.JobType.TRANSLATE,
                status=ProcessingJob.Status.COMPLETED,
            ).first()
            if completed_job is None:
                now = timezone.now()
                completed_job = ProcessingJob.objects.create(
                    user=request.user,
                    paper=paper,
                    job_type=ProcessingJob.JobType.TRANSLATE,
                    status=ProcessingJob.Status.COMPLETED,
                    progress_current=1,
                    progress_total=1,
                    model_name=existing_translation.model_name,
                    started_at=now,
                    completed_at=now,
                )
            return Response(
                {
                    "message": "이미 생성된 번역이 있습니다.",
                    "job": ProcessingJobSerializer(completed_job).data,
                }
            )

        job = ProcessingJob.objects.create(
            user=request.user,
            paper=paper,
            job_type=ProcessingJob.JobType.TRANSLATE,
            status=ProcessingJob.Status.PENDING,
            progress_total=1,
        )
        enqueue_translation_job(job.id)
        return Response(
            {
                "message": "번역 작업을 시작했습니다.",
                "job": ProcessingJobSerializer(job).data,
            },
            status=status.HTTP_202_ACCEPTED,
        )


class PaperQuestionAPIView(APIView):
    """
    논문 질의응답 (RAG) API (RunPod 우선 호출 및 Fallback)
    """
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, arxiv_id, *args, **kwargs):
        paper = get_object_or_404(Paper, arxiv_id=arxiv_id)
        serializer = PaperQuestionRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        question = serializer.validated_data["question"]

        prompt = f"Context:\n{paper.abstract}\n\nQuestion: {question}\nAnswer in Korean:"

        try:
            answer, used_model = call_llm_with_fallback(
                prompt=prompt,
                max_tokens=512,
                fallback_type="question"
            )
            return Response(
                {
                    "question": question,
                    "answer": answer,
                    "model_used": used_model
                },
                status=status.HTTP_200_OK
            )
        except Exception as e:
            logger.error(f"Paper question unhandled error: {e}")
            return Response(
                {"error": str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


class ProcessingJobDetailAPIView(generics.RetrieveAPIView):
    """
    비동기 처리 작업 단일 상세 조회
    """
    serializer_class = ProcessingJobSerializer
    permission_classes = [permissions.IsAuthenticated]
    queryset = ProcessingJob.objects.select_related("paper")
