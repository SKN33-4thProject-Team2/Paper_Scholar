from django.db.models import Count, Exists, OuterRef
from rest_framework.generics import ListAPIView, RetrieveAPIView

from .models import Paper, PaperSummary
from .serializers import PaperDetailSerializer, PaperListSerializer


def paper_api_queryset():
    """목록과 상세 API가 공유하는 집계 포함 Paper QuerySet입니다."""
    return (
        Paper.objects.annotate(
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
        return paper_api_queryset()


class PaperDetailAPIView(RetrieveAPIView):
    serializer_class = PaperDetailSerializer
    lookup_field = "arxiv_id"
    lookup_url_kwarg = "arxiv_id"

    def get_queryset(self):
        return paper_api_queryset()
