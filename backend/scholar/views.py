import logging
from django.db.models import Count, Exists, OuterRef
from django.shortcuts import get_object_or_404
from rest_framework import generics, permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView

from scholar.models import Paper, LibraryEntry, PaperSummary, ProcessingJob
from scholar.serializers import (
    PaperSerializer,
    PaperDetailSerializer,
    ProcessingJobSerializer,
)

logger = logging.getLogger(__name__)


def paper_api_queryset(user=None):
    """
    Paper 목록과 상세 API가 공유하는 기본 QuerySet입니다.
    summary_records는 모델에 존재하지 않으므로 prefetch에서 제외하고,
    sections, translations, library_entries를 최적화하여 가져옵니다.
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


class PaperListView(generics.ListCreateAPIView):
    serializer_class = PaperSerializer
    permission_classes = [permissions.IsAuthenticatedOrReadOnly]

    def get_queryset(self):
        user = self.request.user if self.request.user.is_authenticated else None
        return paper_api_queryset(user)

    def perform_create(self, serializer):
        paper = serializer.save()
        if self.request.user.is_authenticated:
            LibraryEntry.objects.get_or_create(user=self.request.user, paper=paper)


class PaperDetailView(generics.RetrieveUpdateDestroyAPIView):
    serializer_class = PaperDetailSerializer
    permission_classes = [permissions.IsAuthenticatedOrReadOnly]
    lookup_field = "arxiv_id"

    def get_queryset(self):
        user = self.request.user if self.request.user.is_authenticated else None
        return paper_api_queryset(user)


class PaperSaveView(APIView):
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


class ProcessingJobListCreateView(generics.ListCreateAPIView):
    serializer_class = ProcessingJobSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        return ProcessingJob.objects.select_related("paper").filter(
            paper__library_entries__user=self.request.user
        )