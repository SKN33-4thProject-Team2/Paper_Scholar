
from django.conf import settings
from django.db import models


class Paper(models.Model):
    class DownloadStatus(models.TextChoices):
        PENDING = "pending", "대기"
        READY = "ready", "완료"
        FAILED = "failed", "실패"

    arxiv_id = models.CharField(max_length=64, unique=True)
    title = models.CharField(max_length=500)
    authors = models.JSONField(default=list)
    abstract = models.TextField(blank=True)

    entry_url = models.URLField(max_length=1000, blank=True)
    pdf_url = models.URLField(max_length=1000, blank=True)
    pdf_path = models.CharField(max_length=1000, blank=True)
    download_status = models.CharField(
        max_length=20,
        choices=DownloadStatus.choices,
        default=DownloadStatus.PENDING,
    )

    published_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-published_at", "-created_at"]

    def __str__(self):
        return f"{self.arxiv_id} - {self.title}"

# 이 모델은 사용자 한 명이 같은 논문을 서재에 중복 저장하지 못하게 합니다.
class LibraryEntry(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="library_entries",
    )
    paper = models.ForeignKey(
        Paper,
        on_delete=models.CASCADE,
        related_name="library_entries",
    )
    memo = models.TextField(blank=True)
    saved_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-saved_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["user", "paper"],
                name="unique_library_entry_user_paper",
            )
        ]

    def __str__(self):
        return f"{self.user_id} - {self.paper.arxiv_id}"


# 이 모델은 PDF에서 추출한 논문 본문을 절 순서대로 저장합니다. 같은 논문에 동일한 section_order가 중복되지 않게 합니다.
class PaperSection(models.Model):
    paper = models.ForeignKey(
        Paper,
        on_delete=models.CASCADE,
        related_name="sections",
    )
    section_order = models.PositiveIntegerField()
    section_title = models.CharField(max_length=500, blank=True)
    section_text = models.TextField()
    section_html = models.TextField(blank=True)
    extracted_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["section_order"]
        constraints = [
            models.UniqueConstraint(
                fields=["paper", "section_order"],
                name="unique_paper_section_order",
            )
        ]

    def __str__(self):
        return f"{self.paper.arxiv_id} - section {self.section_order}"


# OneToOneField를 사용했기 때문에 논문 하나당 현재 최종 요약 하나만 저장됩니다. 다시 요약할 때는 기존 행을 갱신하는 구조입니다.
class PaperSummary(models.Model):
    paper = models.OneToOneField(
        Paper,
        on_delete=models.CASCADE,
        related_name="summary",
    )
    summary_text = models.TextField()
    model_name = models.CharField(max_length=200, blank=True)
    section_count = models.PositiveIntegerField(default=0)
    chunk_count = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-updated_at"]

    def __str__(self):
        return f"{self.paper.arxiv_id} summary"

# 현재는 summary 번역을 사용하지만, 나중에 전체 본문 번역이 필요할 때 full_text도 사용할 수 있게 준비한 구조입니다.
class Translation(models.Model):
    class TranslationType(models.TextChoices):
        SUMMARY = "summary", "요약문"
        FULL_TEXT = "full_text", "전체 본문"

    paper = models.ForeignKey(
        Paper,
        on_delete=models.CASCADE,
        related_name="translations",
    )
    summary = models.ForeignKey(
        PaperSummary,
        on_delete=models.CASCADE,
        related_name="translations",
    )
    translation_type = models.CharField(
        max_length=20,
        choices=TranslationType.choices,
        default=TranslationType.SUMMARY,
    )
    source_text = models.TextField()
    translated_text = models.TextField()
    source_language = models.CharField(max_length=20, default="en")
    target_language = models.CharField(max_length=20, default="ko")
    model_name = models.CharField(max_length=200, blank=True)
    chunk_count = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-updated_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["summary", "translation_type", "target_language"],
                name="unique_summary_translation_language",
            )
        ]

    def __str__(self):
        return (
            f"{self.paper.arxiv_id} "
            f"{self.translation_type} "
            f"{self.target_language}"
        )



# 다운로드·본문 추출·요약·번역 작업의 진행 상태와 오류를 기록합니다.
class ProcessingJob(models.Model):
    class JobType(models.TextChoices):
        DOWNLOAD = "download", "다운로드"
        EXTRACT = "extract", "본문 추출"
        SUMMARIZE = "summarize", "요약"
        TRANSLATE = "translate", "번역"

    class Status(models.TextChoices):
        PENDING = "pending", "대기"
        RUNNING = "running", "실행 중"
        COMPLETED = "completed", "완료"
        FAILED = "failed", "실패"

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="processing_jobs",
    )
    paper = models.ForeignKey(
        Paper,
        on_delete=models.CASCADE,
        related_name="processing_jobs",
    )
    job_type = models.CharField(
        max_length=20,
        choices=JobType.choices,
    )
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.PENDING,
    )
    progress_current = models.PositiveIntegerField(default=0)
    progress_total = models.PositiveIntegerField(default=0)
    model_name = models.CharField(max_length=200, blank=True)
    error_message = models.TextField(blank=True)
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.paper.arxiv_id} - {self.job_type} - {self.status}"