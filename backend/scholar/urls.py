from django.urls import path, register_converter
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
    PaperExtractAPIView,
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


class ArxivIdConverter:
    """신형 ID와 ``hep-ex/0306056`` 같은 구형 arXiv ID를 허용합니다."""

    # 구형 ID의 앞부분은 영문 카테고리이며, 신형 ID에는 슬래시가 없다.
    # 임의의 두 경로 조각을 허용하면 ``.../sections`` 같은 하위 API 이름까지
    # 논문 ID로 삼킬 수 있으므로 이 형태만 명시적으로 허용한다.
    regex = r"(?:[A-Za-z][A-Za-z0-9.-]*/)?[A-Za-z0-9][A-Za-z0-9._-]*"

    def to_python(self, value):
        return value

    def to_url(self, value):
        return value


register_converter(ArxivIdConverter, "arxiv")

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
    path("papers/<arxiv:arxiv_id>/sections", PaperSectionsAPIView.as_view(), name="paper-sections-noslash"),
    path("papers/<arxiv:arxiv_id>/sections/", PaperSectionsAPIView.as_view(), name="paper-sections"),
    path("papers/<arxiv:arxiv_id>/extract", PaperExtractAPIView.as_view(), name="paper-extract-noslash"),
    path("papers/<arxiv:arxiv_id>/extract/", PaperExtractAPIView.as_view(), name="paper-extract"),
    path("papers/<arxiv:arxiv_id>/summary", PaperSummaryAPIView.as_view(), name="paper-summary-noslash"),
    path("papers/<arxiv:arxiv_id>/summary/", PaperSummaryAPIView.as_view(), name="paper-summary"),
    path("papers/<arxiv:arxiv_id>/summarize", PaperSummarizeAPIView.as_view(), name="paper-summarize-noslash"),
    path("papers/<arxiv:arxiv_id>/summarize/", PaperSummarizeAPIView.as_view(), name="paper-summarize"),
    path("papers/<arxiv:arxiv_id>/translations", PaperTranslationsAPIView.as_view(), name="paper-translations-noslash"),
    path("papers/<arxiv:arxiv_id>/translations/", PaperTranslationsAPIView.as_view(), name="paper-translations"),
    path("papers/<arxiv:arxiv_id>/translate", PaperTranslateAPIView.as_view(), name="paper-translate-noslash"),
    path("papers/<arxiv:arxiv_id>/translate/", PaperTranslateAPIView.as_view(), name="paper-translate"),
    path("papers/<arxiv:arxiv_id>/ask", PaperQuestionAPIView.as_view(), name="paper-question-noslash"),
    path("papers/<arxiv:arxiv_id>/ask/", PaperQuestionAPIView.as_view(), name="paper-question"),

    # 구형 ID가 슬래시를 포함하므로 상세 경로는 하위 리소스 경로 뒤에 둡니다.
    path("papers/<arxiv:arxiv_id>", PaperDetailAPIView.as_view(), name="paper-detail-noslash"),
    path("papers/<arxiv:arxiv_id>/", PaperDetailAPIView.as_view(), name="paper-detail"),
]
