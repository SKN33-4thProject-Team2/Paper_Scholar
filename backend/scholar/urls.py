from django.urls import path

from .views import (
    PaperDetailAPIView,
    PaperListAPIView,
    PaperSectionsAPIView,
    PaperSummaryAPIView,
    PaperTranslationsAPIView,
)


app_name = "scholar"

urlpatterns = [
    path("papers/", PaperListAPIView.as_view(), name="paper-list"),
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
        "papers/<str:arxiv_id>/translations/",
        PaperTranslationsAPIView.as_view(),
        name="paper-translations",
    ),
]
