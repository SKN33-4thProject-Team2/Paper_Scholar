from django.urls import path
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView

from .supervisor_views import (
    SupervisorPlanAPIView,
    SupervisorRunAPIView,
    SupervisorRunDetailAPIView,
)
from .views import (
    ArxivSearchAPIView,
    CurrentUserAPIView,
    PaperDetailAPIView,
    PaperListAPIView,
    PaperQuestionAPIView,
    PaperSaveAPIView,
    PaperSectionsAPIView,
    PaperSummarizeAPIView,
    PaperSummaryAPIView,
    PaperTranslateAPIView,
    PaperTranslationsAPIView,
    ProcessingJobDetailAPIView,
    RegisterAPIView,
    health_check,
)

app_name = "scholar"

urlpatterns = [
    # 헬스 체크
    path("health", health_check, name="health-noslash"),
    path("health/", health_check, name="health"),

    # DeepSearch 플랜
    path("supervisor/plan", SupervisorPlanAPIView.as_view(), name="supervisor-plan-noslash"),
    path("supervisor/plan/", SupervisorPlanAPIView.as_view(), name="supervisor-plan"),

    # Supervisor 그래프 비동기 실행 및 상태 폴링
    path("supervisor/run", SupervisorRunAPIView.as_view(), name="supervisor-run-noslash"),
    path("supervisor/run/", SupervisorRunAPIView.as_view(), name="supervisor-run"),
    path(
        "supervisor/run/<int:pk>",
        SupervisorRunDetailAPIView.as_view(),
        name="supervisor-run-detail-noslash",
    ),
    path(
        "supervisor/run/<int:pk>/",
        SupervisorRunDetailAPIView.as_view(),
        name="supervisor-run-detail",
    ),

    # 사용자 인증
    path("auth/register", RegisterAPIView.as_view(), name="auth-register-noslash"),
    path("auth/register/", RegisterAPIView.as_view(), name="auth-register"),
    path("auth/token", TokenObtainPairView.as_view(), name="auth-token-noslash"),
    path("auth/token/", TokenObtainPairView.as_view(), name="auth-token"),
    path("auth/token/refresh", TokenRefreshView.as_view(), name="auth-token-refresh-noslash"),
    path("auth/token/refresh/", TokenRefreshView.as_view(), name="auth-token-refresh"),
    path("auth/me", CurrentUserAPIView.as_view(), name="auth-me-noslash"),
    path("auth/me/", CurrentUserAPIView.as_view(), name="auth-me"),

    # 논문 검색 및 목록/저장
    path("search", ArxivSearchAPIView.as_view(), name="arxiv-search-noslash"),
    path("search/", ArxivSearchAPIView.as_view(), name="arxiv-search"),
    path("papers", PaperListAPIView.as_view(), name="paper-list-noslash"),
    path("papers/", PaperListAPIView.as_view(), name="paper-list"),
    path("papers/save", PaperSaveAPIView.as_view(), name="paper-save-noslash"),
    path("papers/save/", PaperSaveAPIView.as_view(), name="paper-save"),

    # 비동기 작업 조회
    path("jobs/<int:pk>", ProcessingJobDetailAPIView.as_view(), name="processing-job-detail-noslash"),
    path("jobs/<int:pk>/", ProcessingJobDetailAPIView.as_view(), name="processing-job-detail"),

    # 논문 상세 및 하위 서빙 엔드포인트
    path("papers/<str:arxiv_id>", PaperDetailAPIView.as_view(), name="paper-detail-noslash"),
    path("papers/<str:arxiv_id>/", PaperDetailAPIView.as_view(), name="paper-detail"),
    path("papers/<str:arxiv_id>/sections", PaperSectionsAPIView.as_view(), name="paper-sections-noslash"),
    path("papers/<str:arxiv_id>/sections/", PaperSectionsAPIView.as_view(), name="paper-sections"),
    path("papers/<str:arxiv_id>/summary", PaperSummaryAPIView.as_view(), name="paper-summary-noslash"),
    path("papers/<str:arxiv_id>/summary/", PaperSummaryAPIView.as_view(), name="paper-summary"),
    path("papers/<str:arxiv_id>/summarize", PaperSummarizeAPIView.as_view(), name="paper-summarize-noslash"),
    path("papers/<str:arxiv_id>/summarize/", PaperSummarizeAPIView.as_view(), name="paper-summarize"),
    path("papers/<str:arxiv_id>/translations", PaperTranslationsAPIView.as_view(), name="paper-translations-noslash"),
    path("papers/<str:arxiv_id>/translations/", PaperTranslationsAPIView.as_view(), name="paper-translations"),
    path("papers/<str:arxiv_id>/translate", PaperTranslateAPIView.as_view(), name="paper-translate-noslash"),
    path("papers/<str:arxiv_id>/translate/", PaperTranslateAPIView.as_view(), name="paper-translate"),
    path("papers/<str:arxiv_id>/ask", PaperQuestionAPIView.as_view(), name="paper-question-noslash"),
    path("papers/<str:arxiv_id>/ask/", PaperQuestionAPIView.as_view(), name="paper-question"),
]