import hashlib
import logging
from rest_framework import permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView

from scholar.supervisor_serializers import SupervisorPlanRequestSerializer

logger = logging.getLogger(__name__)


class SupervisorPlanAPIView(APIView):
    """
    DeepSearch 및 Multi-Agent Supervisor 실행 계획 수립 API
    """
    permission_classes = [permissions.AllowAny]

    def _generate_plan(self, query: str, mode: str = "deep") -> dict:
        plan_hash = hashlib.md5(query.encode("utf-8")).hexdigest()[:8]
        return {
            "status": "success",
            "plan_id": f"plan_{plan_hash}",
            "query": query,
            "mode": mode,
            "steps": [
                {
                    "step": 1,
                    "name": "arXiv Query Routing & Search",
                    "action": "search",
                    "description": "arXiv API를 통해 관련 연구 논문 메타데이터 및 초록 수집"
                },
                {
                    "step": 2,
                    "name": "PDF Parsing & Section Analysis",
                    "action": "extract",
                    "description": "본문 섹션 단위 파싱 및 벡터 임베딩 인덱싱"
                },
                {
                    "step": 3,
                    "name": "RunPod GPU LLM Synthesis",
                    "action": "synthesize",
                    "description": "다중 논문 결과 종합 비교 요약 및 학술 인사이트 도출"
                }
            ]
        }

    def get(self, request, *args, **kwargs):
        serializer = SupervisorPlanRequestSerializer(data=request.query_params)
        serializer.is_valid(raise_exception=True)
        query = serializer.validated_data["query"]
        mode = serializer.validated_data.get("mode", "deep")
        return Response(self._generate_plan(query, mode), status=status.HTTP_200_OK)

    def post(self, request, *args, **kwargs):
        serializer = SupervisorPlanRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        query = serializer.validated_data["query"]
        mode = serializer.validated_data.get("mode", "deep")
        return Response(self._generate_plan(query, mode), status=status.HTTP_200_OK)