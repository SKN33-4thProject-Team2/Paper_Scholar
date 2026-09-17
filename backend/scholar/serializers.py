from rest_framework import serializers

from .models import Paper, PaperSection, PaperSummary, ProcessingJob, Translation


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


class ArxivSearchRequestSerializer(serializers.Serializer):
    query = serializers.CharField(max_length=300, trim_whitespace=True)
    max_results = serializers.IntegerField(default=10, min_value=1, max_value=15)
    sort_by = serializers.ChoiceField(
        choices=(
            ("r", "관련도순"),
            ("n", "최신순"),
        ),
        default="r",
    )


class ArxivSearchResultSerializer(serializers.Serializer):
    arxiv_id = serializers.CharField()
    title = serializers.CharField()
    authors = serializers.ListField(child=serializers.CharField())
    abstract = serializers.CharField()
    pdf_url = serializers.URLField(allow_blank=True)


class PaperSaveRequestSerializer(serializers.Serializer):
    papers = ArxivSearchResultSerializer(many=True, allow_empty=False)
    extract_content = serializers.BooleanField(default=True)

    def validate_papers(self, value):
        if len(value) > 15:
            raise serializers.ValidationError("한 번에 최대 15편까지 저장할 수 있습니다.")
        paper_ids = [paper["arxiv_id"] for paper in value]
        if len(paper_ids) != len(set(paper_ids)):
            raise serializers.ValidationError("같은 논문을 중복 선택할 수 없습니다.")
        return value


class ProcessingJobSerializer(serializers.ModelSerializer):
    arxiv_id = serializers.CharField(source="paper.arxiv_id", read_only=True)

    class Meta:
        model = ProcessingJob
        fields = (
            "id",
            "arxiv_id",
            "job_type",
            "status",
            "progress_current",
            "progress_total",
            "model_name",
            "error_message",
            "started_at",
            "completed_at",
            "created_at",
        )
