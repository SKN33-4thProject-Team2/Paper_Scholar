import logging
from rest_framework import permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView

from scholar.supervisor_serializers import SupervisorPlanRequestSerializer

logger = logging.getLogger(__name__)


class SupervisorPlanAPIView(APIView):
    permission_classes = [permissions.AllowAny]

    def get(self, request, *args, **kwargs):
        # GET 쿼리스트링 처리 지원
        serializer = SupervisorPlanRequestSerializer(data=request.query_params)
        serializer.is_valid(raise_exception=True)
        query = serializer.validated_data["query"]
        mode = serializer.validated_data.get("mode", "deep")

        # 기본 플랜 노드 응답 구성
        plan_data = {
            "plan_id": f"plan_{hash(query) & 0xffffffff:x}",
            "query": query,
            "mode": mode,
            "status": "ready",
            "steps": [
                {"step": 1, "name": "arXiv Query Search", "action": "search"},
                {"step": 2, "name": "Abstract & Section Extraction", "action": "extract"},
                {"step": 3, "name": "Comparative Synthesis", "action": "synthesize"}
            ]
        }
        return Response(plan_data, status=status.HTTP_200_OK)

    def post(self, request, *args, **kwargs):
        # POST JSON 바디 처리 지원
        serializer = SupervisorPlanRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        query = serializer.validated_data["query"]
        mode = serializer.validated_data.get("mode", "deep")

        plan_data = {
            "plan_id": f"plan_{hash(query) & 0xffffffff:x}",
            "query": query,
            "mode": mode,
            "status": "ready",
            "steps": [
                {"step": 1, "name": "arXiv Query Search", "action": "search"},
                {"step": 2, "name": "Abstract & Section Extraction", "action": "extract"},
                {"step": 3, "name": "Comparative Synthesis", "action": "synthesize"}
            ]
        }
        return Response(plan_data, status=status.HTTP_200_OK)