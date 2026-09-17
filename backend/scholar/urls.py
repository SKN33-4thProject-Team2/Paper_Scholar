from django.urls import path
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView

from .views import (
    ArxivSearchAPIView,
    PaperDetailAPIView,
    PaperListAPIView,
    PaperQuestionAPIView,
    PaperSaveAPIView,
    PaperSectionsAPIView,
    PaperSummaryAPIView,
    PaperSummarizeAPIView,
    PaperTranslationsAPIView,
    PaperTranslateAPIView,
    ProcessingJobDetailAPIView,
    CurrentUserAPIView,
    RegisterAPIView,
    health_check,
)


app_name = "scholar"

urlpatterns = [
    path("health/", health_check, name="health"),
    path("auth/register/", RegisterAPIView.as_view(), name="auth-register"),
    path("auth/token/", TokenObtainPairView.as_view(), name="auth-token"),
    path(
        "auth/token/refresh/",
        TokenRefreshView.as_view(),
        name="auth-token-refresh",
    ),
    path("auth/me/", CurrentUserAPIView.as_view(), name="auth-me"),
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
    path(
        "papers/<str:arxiv_id>/translate/",
        PaperTranslateAPIView.as_view(),
        name="paper-translate",
    ),
    path(
        "papers/<str:arxiv_id>/ask/",
        PaperQuestionAPIView.as_view(),
        name="paper-question",
    ),
]
