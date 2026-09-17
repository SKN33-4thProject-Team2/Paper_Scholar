from rest_framework import serializers

from .models import Paper, PaperSection, PaperSummary, Translation


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


class PaperSectionSerializer(serializers.ModelSerializer):
    arxiv_id = serializers.CharField(source="paper.arxiv_id", read_only=True)

    class Meta:
        model = PaperSection
        fields = (
            "arxiv_id",
            "section_order",
            "section_title",
            "section_text",
            "section_html",
            "extracted_at",
        )


class PaperSummarySerializer(serializers.ModelSerializer):
    arxiv_id = serializers.CharField(source="paper.arxiv_id", read_only=True)

    class Meta:
        model = PaperSummary
        fields = (
            "arxiv_id",
            "summary_text",
            "model_name",
            "section_count",
            "chunk_count",
            "created_at",
            "updated_at",
        )


class TranslationSerializer(serializers.ModelSerializer):
    arxiv_id = serializers.CharField(source="paper.arxiv_id", read_only=True)

    class Meta:
        model = Translation
        fields = (
            "id",
            "arxiv_id",
            "translation_type",
            "source_language",
            "target_language",
            "source_text",
            "translated_text",
            "model_name",
            "chunk_count",
            "created_at",
            "updated_at",
        )
