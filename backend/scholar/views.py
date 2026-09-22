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
    """
    검색된 논문을 내 서재에 저장
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
    특정 논문의 섹션 본문 목록 조회
    """
    serializer_class = PaperSectionSerializer
    permission_classes = [permissions.IsAuthenticatedOrReadOnly]

    def get_queryset(self):
        arxiv_id = self.kwargs.get("arxiv_id")
        return PaperSection.objects.filter(paper__arxiv_id=arxiv_id).order_by("section_order")


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
    """
    RunPod LLM 모델 서버 호출 및 자동 Fallback 요약 실행 API
    """
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, arxiv_id, *args, **kwargs):
        paper = get_object_or_404(Paper, arxiv_id=arxiv_id)
        prompt = f"Summarize the following paper abstract in Korean:\n\n{paper.abstract}"

        try:
            summary_text, used_model = call_llm_with_fallback(
                prompt=prompt,
                max_tokens=1024,
                fallback_type="summary"
            )

            summary, _ = PaperSummary.objects.update_or_create(
                paper=paper,
                defaults={
                    "summary_text": summary_text,
                    "model_name": used_model,
                },
            )
            return Response(
                {
                    "status": "success",
                    "summary": summary.summary_text,
                    "model_used": used_model
                },
                status=status.HTTP_200_OK,
            )
        except Exception as e:
            logger.error(f"Paper summarize unhandled error: {e}")
            return Response(
                {"error": f"Failed to summarize paper: {str(e)}"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )


class PaperTranslationsAPIView(generics.ListAPIView):
    """
    특정 논문의 번역 목록 조회
    """
    serializer_class = TranslationSerializer
    permission_classes = [permissions.IsAuthenticatedOrReadOnly]

    def get_queryset(self):
        arxiv_id = self.kwargs.get("arxiv_id")
        return Translation.objects.filter(paper__arxiv_id=arxiv_id)


class PaperTranslateAPIView(APIView):
    """
    논문 한국어 번역 API (RunPod 우선 호출 및 Fallback)
    """
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, arxiv_id, *args, **kwargs):
        paper = get_object_or_404(Paper, arxiv_id=arxiv_id)
        source_text = paper.abstract or paper.title
        prompt = f"Translate the following academic paper abstract into natural Korean:\n\n{source_text}"

        try:
            translated_text, used_model = call_llm_with_fallback(
                prompt=prompt,
                max_tokens=1024,
                fallback_type="translation"
            )

            translation, _ = Translation.objects.update_or_create(
                paper=paper,
                translation_type="abstract",
                target_language="ko",
                defaults={
                    "source_language": "en",
                    "source_text": source_text,
                    "translated_text": translated_text,
                    "model_name": used_model,
                },
            )

            return Response(
                {
                    "status": "success",
                    "message": "Translation completed",
                    "translated_text": translation.translated_text,
                    "model_used": used_model
                },
                status=status.HTTP_200_OK,
            )
        except Exception as e:
            logger.error(f"Paper translate unhandled error: {e}")
            return Response(
                {"error": f"Failed to translate paper: {str(e)}"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
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