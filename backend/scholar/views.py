from django.db.models import Count, Exists, OuterRef
from django.shortcuts import get_object_or_404
from rest_framework.decorators import api_view, permission_classes
from rest_framework.generics import ListAPIView, RetrieveAPIView
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

from .models import Paper, PaperSummary
from .serializers import (
    PaperDetailSerializer,
    PaperListSerializer,
    PaperSectionSerializer,
    PaperSummarySerializer,
    TranslationSerializer,
)


@api_view(["GET"])
@permission_classes([AllowAny])
def health_check(_request):
    return Response(
        {
            "status": "ok",
            "service": "paper-scholar-api",
        }
    )


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


class PaperSectionsAPIView(ListAPIView):
    serializer_class = PaperSectionSerializer
    pagination_class = None

    def get_queryset(self):
        paper = get_object_or_404(
            Paper.objects.prefetch_related("sections"),
            arxiv_id=self.kwargs["arxiv_id"],
        )
        return paper.sections.all()


class PaperSummaryAPIView(RetrieveAPIView):
    serializer_class = PaperSummarySerializer

    def get_object(self):
        return get_object_or_404(
            PaperSummary.objects.select_related("paper"),
            paper__arxiv_id=self.kwargs["arxiv_id"],
        )


class PaperTranslationsAPIView(ListAPIView):
    serializer_class = TranslationSerializer
    pagination_class = None

    def get_queryset(self):
        paper = get_object_or_404(Paper, arxiv_id=self.kwargs["arxiv_id"])
        queryset = paper.translations.select_related("paper")

        translation_type = self.request.query_params.get("type")
        if translation_type:
            queryset = queryset.filter(translation_type=translation_type)

        target_language = self.request.query_params.get("target_language")
        if target_language:
            queryset = queryset.filter(target_language=target_language)

        return queryset
