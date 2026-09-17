from rest_framework import serializers

from .models import Paper


class PaperListSerializer(serializers.ModelSerializer):
    section_count = serializers.IntegerField(source="api_section_count", read_only=True)
    translation_count = serializers.IntegerField(source="api_translation_count", read_only=True)
    has_summary = serializers.BooleanField(source="api_has_summary", read_only=True)

    class Meta:
        model = Paper
        fields = (
            "arxiv_id",
            "title",
            "authors",
            "pdf_url",
            "download_status",
            "published_at",
            "created_at",
            "updated_at",
            "section_count",
            "translation_count",
            "has_summary",
        )


class PaperDetailSerializer(PaperListSerializer):
    class Meta(PaperListSerializer.Meta):
        fields = PaperListSerializer.Meta.fields + (
            "abstract",
            "entry_url",
            "pdf_path",
        )
