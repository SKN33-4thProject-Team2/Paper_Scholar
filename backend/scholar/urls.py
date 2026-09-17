from django.urls import path

from .views import PaperDetailAPIView, PaperListAPIView


app_name = "scholar"

urlpatterns = [
    path("papers/", PaperListAPIView.as_view(), name="paper-list"),
    path(
        "papers/<str:arxiv_id>/",
        PaperDetailAPIView.as_view(),
        name="paper-detail",
    ),
]
