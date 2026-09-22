from rest_framework import serializers


class SupervisorPlanRequestSerializer(serializers.Serializer):
    """
    Supervisor DeepSearch Plan 생성 요청 검증 시리얼라이저
    """
    query = serializers.CharField(required=True, allow_blank=False, max_length=500)
    mode = serializers.CharField(required=False, default="deep", max_length=50)
    max_steps = serializers.IntegerField(required=False, default=3, min_value=1, max_value=10)


class SupervisorPlanResponseSerializer(serializers.Serializer):
    """
    Supervisor DeepSearch Plan 응답 구조체
    """
    plan_id = serializers.CharField()
    query = serializers.CharField()
    steps = serializers.ListField(child=serializers.DictField())
    status = serializers.CharField()