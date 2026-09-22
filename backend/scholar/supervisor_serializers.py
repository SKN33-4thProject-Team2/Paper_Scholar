from rest_framework import serializers

from .models import SupervisorRun


class SupervisorPlanRequestSerializer(serializers.Serializer):
    """실행 계획 미리보기 요청."""

    query = serializers.CharField(required=True, allow_blank=False, max_length=2000)
    mode = serializers.CharField(required=False, default="deep", max_length=50)


class SupervisorRunRequestSerializer(serializers.Serializer):
    """Supervisor 실행 요청. thread_id를 넘기면 이전 턴을 이어서 처리한다."""

    query = serializers.CharField(required=True, allow_blank=False, max_length=2000)
    thread_id = serializers.CharField(required=False, allow_blank=True, max_length=64)


class SupervisorRunSerializer(serializers.ModelSerializer):
    """실행 상태 폴링 응답."""

    class Meta:
        model = SupervisorRun
        fields = (
            "id",
            "thread_id",
            "query",
            "status",
            "plan",
            "node_history",
            "response",
            "papers",
            "sources",
            "error_message",
            "created_at",
            "started_at",
            "completed_at",
        )
        read_only_fields = fields
