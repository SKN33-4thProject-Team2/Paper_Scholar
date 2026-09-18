from rest_framework import serializers


class SupervisorCommandSerializer(serializers.Serializer):
    message = serializers.CharField(
        min_length=2,
        max_length=2000,
        trim_whitespace=True,
    )
