from django.db.models import Count, Exists, OuterRef
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework.decorators import api_view, permission_classes
from rest_framework.generics import CreateAPIView, ListAPIView, RetrieveAPIView
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework import status
from rest_framework.views import APIView

from .jobs import (
    enqueue_extraction_job,
    enqueue_summary_job,
    enqueue_translation_job,
)
from .models import LibraryEntry, Paper, PaperSummary, ProcessingJob, Translation
from .serializers import (
    ArxivSearchRequestSerializer,
    ArxivSearchResultSerializer,
    PaperDetailSerializer,
    PaperListSerializer,
    PaperQuestionRequestSerializer,
    PaperSectionSerializer,
    PaperSaveRequestSerializer,
    PaperSummarizeRequestSerializer,
    PaperSummarySerializer,
    PaperTranslateRequestSerializer,
    ProcessingJobSerializer,
    RegisterSerializer,
    TranslationSerializer,
    UserSerializer,
)


class RegisterAPIView(CreateAPIView):
    permission_classes = [AllowAny]
    serializer_class = RegisterSerializer

    def create(self, request, *args, **kwargs):
        request_serializer = self.get_serializer(data=request.data)
        request_serializer.is_valid(raise_exception=True)
        user = request_serializer.save()
        return Response(UserSerializer(user).data, status=status.HTTP_201_CREATED)


class CurrentUserAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        return Response(UserSerializer(request.user).data)


def save_papers_and_create_jobs(
    papers: list[dict],
    *,
    extract_content: bool,
    user,
) -> tuple[str, list[ProcessingJob]]:
    """기존 저장 흐름으로 메타데이터를 보존하고 추출 작업을 등록합니다."""
    from src.feature.search import ArxivSearchBot
    from src.services.django_paper_repository import normalize_arxiv_id

    legacy_papers = [
        {
            "id": paper["arxiv_id"],
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


def run_arxiv_search(query: str, max_results: int, sort_by: str) -> list[dict]:
    """기존 ArxivSearchBot의 제목 검색 기능을 HTTP 계층에서 호출합니다."""
    from src.feature.search import ArxivSearchBot

    clean_query = query.strip().replace('"', "")
    bot = ArxivSearchBot()
    papers = bot.search_papers(
        final_query=f'ti:"{clean_query}"',
        sort_by=sort_by,
        max_results=max_results,
    )
    return [
        {
            "arxiv_id": paper["id"],
            "title": paper["title"],
            "authors": [
                author.strip()
                for author in str(paper.get("authors") or "").split(",")
                if author.strip()
            ],
            "abstract": paper.get("summary") or "",
            "pdf_url": paper.get("pdf_url") or "",
        }
        for paper in papers
    ]


@api_view(["GET"])
@permission_classes([AllowAny])
def health_check(_request):
    return Response(
        {
            "status": "ok",
            "service": "paper-scholar-api",
        }
    )


class ArxivSearchAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        request_serializer = ArxivSearchRequestSerializer(data=request.data)
        request_serializer.is_valid(raise_exception=True)
        params = request_serializer.validated_data

        try:
            results = run_arxiv_search(
                query=params["query"],
                max_results=params["max_results"],
                sort_by=params["sort_by"],
            )
        except Exception as exc:
            return Response(
                {"detail": f"arXiv 검색 중 오류가 발생했습니다: {exc}"},
                status=status.HTTP_502_BAD_GATEWAY,
            )

        result_serializer = ArxivSearchResultSerializer(results, many=True)
        return Response(
            {
                "query": params["query"],
                "sort_by": params["sort_by"],
                "count": len(results),
                "results": result_serializer.data,
            }
        )


class PaperSaveAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
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


class ProcessingJobDetailAPIView(RetrieveAPIView):
    serializer_class = ProcessingJobSerializer

    def get_queryset(self):
        return ProcessingJob.objects.select_related("paper").filter(
            paper__library_entries__user=self.request.user
        )


def paper_api_queryset(user=None):
    """목록과 상세 API가 공유하는 집계 포함 Paper QuerySet입니다."""
    queryset = Paper.objects.all()
    if user is not None:
        queryset = queryset.filter(library_entries__user=user)
    return (
        queryset.annotate(
            api_section_count=Count("sections", distinct=True),
            api_translation_count=Count("translations", distinct=True),
            api_has_summary=Exists(
                PaperSummary.objects.filter(paper_id=OuterRef("pk"))
            ),
        )
        .order_by("-published_at", "-created_at")
    )


class PaperListAPIView(ListAPIView):
    serializer_class = PaperListSerializer

    def get_queryset(self):
        return paper_api_queryset(self.request.user)


class PaperDetailAPIView(RetrieveAPIView):
    serializer_class = PaperDetailSerializer
    lookup_field = "arxiv_id"
    lookup_url_kwarg = "arxiv_id"

    def get_queryset(self):
        return paper_api_queryset(self.request.user)


class PaperSectionsAPIView(ListAPIView):
    serializer_class = PaperSectionSerializer
    pagination_class = None

    def get_queryset(self):
        paper = get_object_or_404(
            Paper.objects.prefetch_related("sections"),
            arxiv_id=self.kwargs["arxiv_id"],
            library_entries__user=self.request.user,
        )
        return paper.sections.all()


class PaperSummaryAPIView(RetrieveAPIView):
    serializer_class = PaperSummarySerializer

    def get_object(self):
        return get_object_or_404(
            PaperSummary.objects.select_related("paper"),
            paper__arxiv_id=self.kwargs["arxiv_id"],
            paper__library_entries__user=self.request.user,
        )


class PaperSummarizeAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, arxiv_id: str):
        request_serializer = PaperSummarizeRequestSerializer(data=request.data)
        request_serializer.is_valid(raise_exception=True)
        force = request_serializer.validated_data["force"]
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
            status__in=(
                ProcessingJob.Status.PENDING,
                ProcessingJob.Status.RUNNING,
            ),
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
                job_type=ProcessingJob.JobType.SUMMARIZE,
                status=ProcessingJob.Status.COMPLETED,
                user=request.user,
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


class PaperTranslationsAPIView(ListAPIView):
    serializer_class = TranslationSerializer
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
    permission_classes = [IsAuthenticated]

    def post(self, request, arxiv_id: str):
        request_serializer = PaperTranslateRequestSerializer(data=request.data)
        request_serializer.is_valid(raise_exception=True)
        params = request_serializer.validated_data
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
            status__in=(
                ProcessingJob.Status.PENDING,
                ProcessingJob.Status.RUNNING,
            ),
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
                job_type=ProcessingJob.JobType.TRANSLATE,
                status=ProcessingJob.Status.COMPLETED,
                user=request.user,
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
    permission_classes = [IsAuthenticated]

    def post(self, request, arxiv_id: str):
        request_serializer = PaperQuestionRequestSerializer(data=request.data)
        request_serializer.is_valid(raise_exception=True)
        paper = get_object_or_404(
            Paper.objects.prefetch_related("sections", "translations"),
            arxiv_id=arxiv_id,
            library_entries__user=request.user,
        )
        if not paper.sections.exists():
            return Response(
                {"detail": "질문할 본문 섹션이 없습니다. 먼저 본문을 추출해 주세요."},
                status=status.HTTP_409_CONFLICT,
            )

        try:
            from .services.rag_service import answer_paper_question

            result = answer_paper_question(
                paper,
                request_serializer.validated_data["question"],
            )
        except Exception as exc:
            return Response(
                {"detail": f"논문 질의응답 중 오류가 발생했습니다: {exc}"},
                status=status.HTTP_502_BAD_GATEWAY,
            )
        return Response(result)
