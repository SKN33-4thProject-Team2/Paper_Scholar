from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .supervisor_serializers import SupervisorCommandSerializer
from .supervisor_service import SupervisorPlanner


class SupervisorPlanAPIView(APIView):
    """Translate one chat command into calls to the existing feature APIs."""

    permission_classes = [IsAuthenticated]

    def post(self, request):
        request_serializer = SupervisorCommandSerializer(data=request.data)
        request_serializer.is_valid(raise_exception=True)
        try:
            plan = SupervisorPlanner().plan(
                request_serializer.validated_data["message"]
            )
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
        return Response(plan.model_dump())
