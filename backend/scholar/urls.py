from django.urls import path

from .views import (
    ArxivSearchAPIView,
    PaperDetailAPIView,
    PaperListAPIView,
    PaperSaveAPIView,
    PaperSectionsAPIView,
    PaperSummaryAPIView,
    PaperSummarizeAPIView,
    PaperTranslationsAPIView,
    ProcessingJobDetailAPIView,
    health_check,
)


app_name = "scholar"

urlpatterns = [
    path("health/", health_check, name="health"),
    path("search/", ArxivSearchAPIView.as_view(), name="arxiv-search"),
    path("papers/", PaperListAPIView.as_view(), name="paper-list"),
    path("papers/save/", PaperSaveAPIView.as_view(), name="paper-save"),
    path(
        "jobs/<int:pk>/",
        ProcessingJobDetailAPIView.as_view(),
        name="processing-job-detail",
    ),
    path(
        "papers/<str:arxiv_id>/",
        PaperDetailAPIView.as_view(),
        name="paper-detail",
    ),
    path(
        "papers/<str:arxiv_id>/sections/",
        PaperSectionsAPIView.as_view(),
        name="paper-sections",
    ),
    path(
        "papers/<str:arxiv_id>/summary/",
        PaperSummaryAPIView.as_view(),
        name="paper-summary",
    ),
    path(
        "papers/<str:arxiv_id>/summarize/",
        PaperSummarizeAPIView.as_view(),
        name="paper-summarize",
    ),
    path(
        "papers/<str:arxiv_id>/translations/",
        PaperTranslationsAPIView.as_view(),
        name="paper-translations",
    ),
]
