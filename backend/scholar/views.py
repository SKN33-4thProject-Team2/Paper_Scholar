from django.db.models import Count, Exists, OuterRef
from django.shortcuts import get_object_or_404
from rest_framework.decorators import api_view, permission_classes
from rest_framework.generics import ListAPIView, RetrieveAPIView
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework import status
from rest_framework.views import APIView

from .models import Paper, PaperSummary
from .serializers import (
    ArxivSearchRequestSerializer,
    ArxivSearchResultSerializer,
    PaperDetailSerializer,
    PaperListSerializer,
    PaperSectionSerializer,
    PaperSummarySerializer,
    TranslationSerializer,
)


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
    permission_classes = [AllowAny]

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
