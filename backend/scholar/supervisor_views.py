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


class SupervisorRunAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        from .models import SupervisorRun
        from .supervisor_serializers import SupervisorRunSerializer
        runs = SupervisorRun.objects.filter(user=request.user).order_by('-pk')[:30]
        return Response(SupervisorRunSerializer(runs, many=True).data)

    def post(self, request):
        from uuid import uuid4
        from django.contrib.auth import get_user_model
        from django.db import transaction
        from .models import SupervisorRun
        from .jobs import enqueue_supervisor_run
        from .supervisor_serializers import SupervisorRunRequestSerializer, SupervisorRunSerializer
        serializer = SupervisorRunRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        thread_id = str(data.get('thread_id') or uuid4())
        with transaction.atomic():
            # Serialize submissions from one user; conversation state must not race.
            get_user_model().objects.select_for_update().get(pk=request.user.pk)
            active = SupervisorRun.objects.filter(user=request.user,
                status__in=['pending', 'running']).first()
            if active:
                return Response({'detail': '진행 중인 요청이 있습니다.',
                                 'run': SupervisorRunSerializer(active).data}, status=409)
            run = SupervisorRun.objects.create(user=request.user, thread_id=thread_id, query=data['message'])
            transaction.on_commit(lambda: enqueue_supervisor_run(run.pk))
        return Response(SupervisorRunSerializer(run).data, status=202)


class SupervisorRunDetailAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, pk):
        from django.shortcuts import get_object_or_404
        from .models import SupervisorRun
        from .supervisor_serializers import SupervisorRunSerializer
        run = get_object_or_404(SupervisorRun, pk=pk, user=request.user)
        return Response(SupervisorRunSerializer(run).data)
