from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from rest_framework import serializers

from .models import Paper, PaperSection, PaperSummary, ProcessingJob, Translation


User = get_user_model()


class UserSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ("id", "username", "email", "date_joined")
        read_only_fields = fields


class RegisterSerializer(serializers.Serializer):
    username = serializers.CharField(max_length=150)
    email = serializers.EmailField()
    password = serializers.CharField(write_only=True, min_length=8)
    password_confirm = serializers.CharField(write_only=True, min_length=8)

    def validate_username(self, value):
        clean_value = value.strip()
        if User.objects.filter(username__iexact=clean_value).exists():
            raise serializers.ValidationError("이미 사용 중인 아이디입니다.")
        return clean_value

    def validate_email(self, value):
        clean_value = value.strip().lower()
        if User.objects.filter(email__iexact=clean_value).exists():
            raise serializers.ValidationError("이미 사용 중인 이메일입니다.")
        return clean_value

    def validate(self, attrs):
        if attrs["password"] != attrs["password_confirm"]:
            raise serializers.ValidationError(
                {"password_confirm": "비밀번호가 일치하지 않습니다."}
            )
        candidate = User(username=attrs["username"], email=attrs["email"])
        validate_password(attrs["password"], user=candidate)
        return attrs

    def create(self, validated_data):
        validated_data.pop("password_confirm")
        return User.objects.create_user(**validated_data)


class PaperListSerializer(serializers.ModelSerializer):
    section_count = serializers.IntegerField(source="api_section_count", read_only=True)
    translation_count = serializers.IntegerField(source="api_translation_count", read_only=True)
    has_summary = serializers.BooleanField(source="api_has_summary", read_only=True)
    latest_extraction_job = serializers.SerializerMethodField()

    def get_latest_extraction_job(self, paper):
        request = self.context.get("request")
        if request is None or not request.user.is_authenticated:
            return None

        job = paper.processing_jobs.filter(
            user=request.user,
            job_type=ProcessingJob.JobType.EXTRACT,
        ).first()
        return ProcessingJobSerializer(job).data if job is not None else None

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
            "latest_extraction_job",
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
    translated_text = serializers.SerializerMethodField()
    translation_model_name = serializers.SerializerMethodField()
    translation_chunk_count = serializers.SerializerMethodField()

    @staticmethod
    def _korean_translation(summary):
        if hasattr(summary, "_korean_translation_cache"):
            return summary._korean_translation_cache
        prefetched = getattr(summary, "korean_translations", None)
        if prefetched is not None:
            translation = prefetched[0] if prefetched else None
        else:
            translation = summary.translations.filter(
                translation_type=Translation.TranslationType.SUMMARY,
                target_language="ko",
            ).first()
        summary._korean_translation_cache = translation
        return translation

    def get_translated_text(self, summary):
        translation = self._korean_translation(summary)
        return translation.translated_text if translation else ""

    def get_translation_model_name(self, summary):
        translation = self._korean_translation(summary)
        return translation.model_name if translation else ""

    def get_translation_chunk_count(self, summary):
        translation = self._korean_translation(summary)
        return translation.chunk_count if translation else 0

    class Meta:
        model = PaperSummary
        fields = (
            "arxiv_id",
            "summary_text",
            "translated_text",
            "model_name",
            "translation_model_name",
            "section_count",
            "chunk_count",
            "translation_chunk_count",
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


class PaperSummarizeRequestSerializer(serializers.Serializer):
    force = serializers.BooleanField(default=False)


class PaperTranslateRequestSerializer(serializers.Serializer):
    target_language = serializers.ChoiceField(
        choices=(("ko", "한국어"),),
        default="ko",
    )
    force = serializers.BooleanField(default=False)


class PaperQuestionRequestSerializer(serializers.Serializer):
    question = serializers.CharField(
        min_length=2,
        max_length=2000,
        trim_whitespace=True,
    )


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
