import logging
from uuid import uuid4

from rest_framework import permissions, status
from rest_framework.generics import RetrieveAPIView
from rest_framework.response import Response
from rest_framework.views import APIView

from .jobs import enqueue_supervisor_run
from .models import SupervisorRun
from .supervisor_serializers import (
    SupervisorPlanRequestSerializer,
    SupervisorRunRequestSerializer,
    SupervisorRunSerializer,
)
from .supervisor_service import build_plan

logger = logging.getLogger(__name__)


class SupervisorPlanAPIView(APIView):
    """LangGraph Supervisor가 어떤 Agent를 쓸지 미리 보여준다(실행하지 않음)."""

    permission_classes = [permissions.AllowAny]

    def _plan(self, data):
        serializer = SupervisorPlanRequestSerializer(data=data)
        serializer.is_valid(raise_exception=True)
        query = serializer.validated_data["query"]
        try:
            return Response(build_plan(query), status=status.HTTP_200_OK)
        except Exception as exc:
            logger.error("Supervisor plan generation failed: %s", exc)
            return Response(
                {"error": f"실행 계획을 만들지 못했습니다: {exc}"},
                status=status.HTTP_502_BAD_GATEWAY,
            )

    def get(self, request, *args, **kwargs):
        return self._plan(request.query_params)

    def post(self, request, *args, **kwargs):
        return self._plan(request.data)


class SupervisorRunAPIView(APIView):
    """요청 한 번으로 그래프 전체를 비동기 실행한다. 진행 상황은 폴링으로 본다."""

    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, *args, **kwargs):
        serializer = SupervisorRunRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        query = serializer.validated_data["query"]
        thread_id = (
            serializer.validated_data.get("thread_id")
            or f"web-{uuid4().hex[:12]}"
        )

        try:
            plan = build_plan(query, thread_id=thread_id)
        except Exception as exc:
            logger.error("Supervisor plan generation failed: %s", exc)
            return Response(
                {"error": f"실행 계획을 만들지 못했습니다: {exc}"},
                status=status.HTTP_502_BAD_GATEWAY,
            )

        run = SupervisorRun.objects.create(
            user=request.user if request.user.is_authenticated else None,
            thread_id=thread_id,
            query=query,
            plan=plan["steps"],
        )

        # 되묻기만 필요한 요청은 그래프를 돌리지 않고 바로 질문을 돌려준다.
        if plan["needs_clarification"]:
            run.status = SupervisorRun.Status.NEEDS_INPUT
            run.response = plan["clarification_question"]
            run.save(update_fields=("status", "response"))
        else:
            enqueue_supervisor_run(run.id)

        return Response(
            SupervisorRunSerializer(run).data,
            status=status.HTTP_202_ACCEPTED,
        )


class SupervisorRunDetailAPIView(RetrieveAPIView):
    """실행 상태·결과 조회."""

    serializer_class = SupervisorRunSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        return SupervisorRun.objects.filter(user=self.request.user)
