import logging
from rest_framework import permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView

from scholar.supervisor_serializers import SupervisorPlanRequestSerializer
from scholar.supervisor_service import generate_supervisor_plan

logger = logging.getLogger(__name__)


class SupervisorPlanAPIView(APIView):
    """
    논문 DeepSearch 및 다단계 실행 계획(Supervisor Plan) API
    GET / POST 두 방식 모두 완벽히 지원
    """
    permission_classes = [permissions.AllowAny]

    def get(self, request, *args, **kwargs):
        # 프론트엔드 GET 쿼리스트링 파라미터 처리
        query = request.query_params.get("query", "")
        mode = request.query_params.get("mode", "deep")

        if not query:
            return Response(
                {"error": "query 파라미터가 필요합니다."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            plan = generate_supervisor_plan(query=query, mode=mode)
            return Response(plan, status=status.HTTP_200_OK)
        except Exception as e:
            logger.error(f"Supervisor plan generation failed: {e}")
            return Response(
                {"error": f"Failed to generate plan: {str(e)}"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

    def post(self, request, *args, **kwargs):
        # POST JSON 바디 처리
        serializer = SupervisorPlanRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        query = serializer.validated_data["query"]
        mode = serializer.validated_data.get("mode", "deep")

        try:
            plan = generate_supervisor_plan(query=query, mode=mode)
            return Response(plan, status=status.HTTP_200_OK)
        except Exception as e:
            logger.error(f"Supervisor plan generation failed: {e}")
            return Response(
                {"error": f"Failed to generate plan: {str(e)}"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )