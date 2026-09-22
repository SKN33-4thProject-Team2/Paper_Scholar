import logging
import os
import urllib.request
import xml.etree.ElementTree as ET
import requests

from django.contrib.auth import get_user_model
from django.db.models import Count, Exists, OuterRef
from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from rest_framework import generics, permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView

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

User = get_user_model()
logger = logging.getLogger(__name__)


# -------------------------------------------------------------------------
# 1. 헬스 체크
# -------------------------------------------------------------------------
def health_check(request):
    """
    서버 상태 점검용 엔드포인트
    """
    return JsonResponse({"status": "ok", "service": "Paper Scholar Backend"})


# -------------------------------------------------------------------------
# 2. 인증 관련 뷰
# -------------------------------------------------------------------------
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
    현재 로그인된 사용자 정보 조회 API
    """
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, *args, **kwargs):
        serializer = UserSerializer(request.user)
        return Response(serializer.data, status=status.HTTP_200_OK)


# -------------------------------------------------------------------------
# 3. 논문 쿼리셋 공통 함수
# -------------------------------------------------------------------------
def paper_api_queryset(user=None):
    """
    Paper 목록/상세 API 공통 쿼리셋.
    summary_records 역참조 에러를 방지하고 관련 필드만 최적화하여 조회합니다.
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
        .order_by("-updated_at")
    )
    if user is not None and getattr(user, "is_authenticated", False):
        queryset = queryset.filter(library_entries__user=user)
    return queryset


# -------------------------------------------------------------------------
# 4. Arxiv 검색 및 논문 CRUD 뷰
# -------------------------------------------------------------------------
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

        search_url = f"http://export.arxiv.org/api/query?search_query=all:{query}&start=0&max_results={max_results}"
        try:
            with urllib.request.urlopen(search_url, timeout=10) as response:
                xml_data = response.read()
            root = ET.fromstring(xml_data)
            ns = {"atom": "http://www.w3.org/2005/Atom"}

            results = []
            for entry in root.findall("atom:entry", ns):
                raw_id = entry.find("atom:id", ns).text
                arxiv_id = raw_id.split("/abs/")[-1]
                title = entry.find("atom:title", ns).text.strip().replace("\n", " ")
                abstract = entry.find("atom:summary", ns).text.strip().replace("\n", " ")
                authors = [
                    author.find("atom:name", ns).text
                    for author in entry.findall("atom:author", ns)
                ]

                pdf_url = ""
                for link in entry.findall("atom:link", ns):
                    if link.attrib.get("title") == "pdf":
                        pdf_url = link.attrib.get("href")
                        break

                results.append(
                    {
                        "arxiv_id": arxiv_id,
                        "title": title,
                        "authors": authors,
                        "abstract": abstract,
                        "pdf_url": pdf_url,
                    }
                )

            res_serializer = ArxivSearchResultSerializer(results, many=True)
            return Response(res_serializer.data, status=status.HTTP_200_OK)
        except Exception as e:
            logger.error(f"Arxiv search error: {e}")
            return Response(
                {"error": "Failed to search Arxiv"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )


class PaperListAPIView(generics.ListCreateAPIView):
    """
    논문 목록 및 등록 API
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
    논문 상세/수정/삭제 API
    """
    serializer_class = PaperDetailSerializer
    permission_classes = [permissions.IsAuthenticatedOrReadOnly]
    lookup_field = "arxiv_id"

    def get_queryset(self):
        user = self.request.user if self.request.user.is_authenticated else None
        return paper_api_queryset(user)


class PaperSaveAPIView(APIView):
    """
    Arxiv 검색 결과 논문 저장 API
    """
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, *args, **kwargs):
        arxiv_id = request.data.get("arxiv_id") or request.data.get("id")
        title = request.data.get("title", "")
        authors = request.data.get("authors", [])
        abstract = request.data.get("summary") or request.data.get("abstract", "")

        if not arxiv_id:
            return Response(
                {"detail": "arxiv_id가 필요합니다."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        paper, _ = Paper.objects.update_or_create(
            arxiv_id=arxiv_id,
            defaults={
                "title": title,
                "authors": authors,
                "abstract": abstract,
                "download_status": Paper.DownloadStatus.READY,
            },
        )
        LibraryEntry.objects.get_or_create(user=request.user, paper=paper)

        return Response(
            {
                "status": "success",
                "message": "Paper saved to library successfully",
                "paper_id": arxiv_id,
                "jobs": [{"job_id": f"job_{arxiv_id}", "status": "completed"}],
            },
            status=status.HTTP_201_CREATED,
        )


class PaperSectionsAPIView(generics.ListAPIView):
    """
    논문 섹션 목록 조회 API
    """
    serializer_class = PaperSectionSerializer
    permission_classes = [permissions.IsAuthenticatedOrReadOnly]

    def get_queryset(self):
<<<<<<< HEAD
        arxiv_id = self.kwargs.get("arxiv_id")
        return PaperSection.objects.filter(paper__arxiv_id=arxiv_id).order_by("section_order")


# -------------------------------------------------------------------------
# 5. 요약/번역/질의응답 (RunPod LLM 연동)
# -------------------------------------------------------------------------
class PaperSummaryAPIView(generics.RetrieveAPIView):
    """
    논문 요약 결과 조회 API
    """
    serializer_class = PaperSummarySerializer
    permission_classes = [permissions.IsAuthenticatedOrReadOnly]

    def get_object(self):
        arxiv_id = self.kwargs.get("arxiv_id")
        return get_object_or_404(PaperSummary, paper__arxiv_id=arxiv_id)


class PaperSummarizeAPIView(APIView):
    """
    RunPod LLM 모델 서버(Cloudflare 터널)로 요약 생성 요청
    """
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, arxiv_id, *args, **kwargs):
        paper = get_object_or_404(Paper, arxiv_id=arxiv_id)
        runpod_url = os.getenv("RUNPOD_API_URL", "https://llm.skn33-project.store").rstrip("/")

        try:
            payload = {
                "prompt": f"Summarize the following paper abstract:\n\n{paper.abstract}",
                "max_tokens": 1024,
            }
            res = requests.post(f"{runpod_url}/generate", json=payload, timeout=60)

            if res.status_code == 200:
                summary_text = res.json().get("text", res.text)
            else:
                summary_text = f"LLM Inference Response ({res.status_code}): {res.text[:200]}"

            summary, _ = PaperSummary.objects.update_or_create(
                paper=paper,
                defaults={
                    "summary_text": summary_text,
                    "model_name": "runpod-llm",
                },
            )
            return Response(
                {"status": "success", "summary": summary.summary_text},
                status=status.HTTP_200_OK,
            )
        except Exception as e:
            logger.error(f"RunPod inference failed: {e}")
            return Response(
                {"error": f"Failed to infer from RunPod: {str(e)}"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )


class PaperTranslationsAPIView(generics.ListAPIView):
    """
    논문 번역 결과 조회 API (urls.py 매핑용 복수형 s)
    """
    serializer_class = TranslationSerializer
    permission_classes = [permissions.IsAuthenticatedOrReadOnly]

    def get_queryset(self):
        arxiv_id = self.kwargs.get("arxiv_id")
        return Translation.objects.filter(paper__arxiv_id=arxiv_id)


class PaperTranslateAPIView(APIView):
    """
    논문 번역 요청 API
    """
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, arxiv_id, *args, **kwargs):
        paper = get_object_or_404(Paper, arxiv_id=arxiv_id)
        return Response(
            {"status": "success", "message": "Translation requested"},
            status=status.HTTP_200_OK,
        )


class PaperQuestionAPIView(APIView):
    """
    논문 질의응답(RAG) 요청 API
    """
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, arxiv_id, *args, **kwargs):
        paper = get_object_or_404(Paper, arxiv_id=arxiv_id)
        serializer = PaperQuestionRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        question = serializer.validated_data["question"]

        runpod_url = os.getenv("RUNPOD_API_URL", "https://llm.skn33-project.store").rstrip("/")
        try:
            payload = {
                "prompt": f"Context:\n{paper.abstract}\n\nQuestion: {question}\nAnswer:",
                "max_tokens": 512,
            }
            res = requests.post(f"{runpod_url}/generate", json=payload, timeout=60)
            answer = res.json().get("text", res.text) if res.status_code == 200 else res.text
            return Response({"question": question, "answer": answer}, status=status.HTTP_200_OK)
        except Exception as e:
            return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


# -------------------------------------------------------------------------
# 6. 작업 상세 조회 뷰
# -------------------------------------------------------------------------
class ProcessingJobDetailAPIView(generics.RetrieveAPIView):
    """
    비동기 처리 작업 단일 상세 조회 API
    """
    serializer_class = ProcessingJobSerializer
    permission_classes = [permissions.IsAuthenticated]
    queryset = ProcessingJob.objects.select_related("paper")
=======
        return ProcessingJob.objects.select_related("paper").filter(
            paper__library_entries__user=self.request.user
        )
>>>>>>> 9accb5e2011d05379cae6c5dc39ae2eb53ddd792
