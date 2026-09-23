from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.authentication import JWTAuthentication

from .supervisor_serializers import (
    SupervisorCommandSerializer,
    SupervisorPlanRequestSerializer,
)
from .supervisor_service import SupervisorPlanner


class SupervisorPlanAPIView(APIView):
    """자연어 요청을 기존 논문 기능으로 실행 가능한 계획으로 변환합니다."""

    authentication_classes = [JWTAuthentication]
    permission_classes = [IsAuthenticated]

    @staticmethod
    def _build_plan(message: str) -> Response:
        try:
            plan = SupervisorPlanner().plan(message)
        except ValueError as exc:
            return Response(
                {"detail": str(exc)},
                status=status.HTTP_400_BAD_REQUEST,
            )
        except Exception as exc:
            return Response(
                {"detail": f"Supervisor가 요청을 해석하지 못했습니다: {exc}"},
                status=status.HTTP_502_BAD_GATEWAY,
            )
        return Response(plan.model_dump(), status=status.HTTP_200_OK)

    def get(self, request, *args, **kwargs):
        """기존 ``?query=`` 호출도 같은 자연어 계획기로 처리합니다."""
        serializer = SupervisorPlanRequestSerializer(data=request.query_params)
        serializer.is_valid(raise_exception=True)
        return self._build_plan(serializer.validated_data["query"])

    def post(self, request, *args, **kwargs):
        serializer = SupervisorCommandSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        return self._build_plan(serializer.validated_data["message"])
