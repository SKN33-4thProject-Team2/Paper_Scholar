from rest_framework import serializers


class SupervisorCommandSerializer(serializers.Serializer):
    """웹 채팅에서 전달하는 자연어 Supervisor 명령입니다."""

    message = serializers.CharField(
        min_length=2,
        max_length=2000,
        trim_whitespace=True,
    )


class SupervisorPlanRequestSerializer(serializers.Serializer):
    """기존 GET ``query`` 호출과의 호환성을 유지합니다."""

    query = serializers.CharField(
        min_length=2,
        max_length=2000,
        trim_whitespace=True,
    )
