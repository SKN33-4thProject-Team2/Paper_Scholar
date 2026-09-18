from django.contrib import admin

from .models import (
    LibraryEntry,
    Paper,
    PaperSection,
    PaperSummary,
    ProcessingJob,
    Translation,
)


@admin.register(Paper)
class PaperAdmin(admin.ModelAdmin):
    list_display = (
        "arxiv_id",
        "title",
        "download_status",
        "published_at",
        "updated_at",
    )
    search_fields = ("arxiv_id", "title")
    list_filter = ("download_status",)


@admin.register(LibraryEntry)
class LibraryEntryAdmin(admin.ModelAdmin):
    list_display = ("user", "paper", "saved_at")
    search_fields = (
        "user__username",
        "paper__arxiv_id",
        "paper__title",
    )


@admin.register(PaperSection)
class PaperSectionAdmin(admin.ModelAdmin):
    list_display = (
        "paper",
        "section_order",
        "section_title",
        "extracted_at",
    )
    search_fields = (
        "paper__arxiv_id",
        "paper__title",
        "section_title",
    )


@admin.register(PaperSummary)
class PaperSummaryAdmin(admin.ModelAdmin):
    list_display = (
        "paper",
        "model_name",
        "section_count",
        "chunk_count",
        "updated_at",
    )
    search_fields = (
        "paper__arxiv_id",
        "paper__title",
    )


@admin.register(Translation)
class TranslationAdmin(admin.ModelAdmin):
    list_display = (
        "paper",
        "translation_type",
        "source_language",
        "target_language",
        "model_name",
        "updated_at",
    )
    search_fields = (
        "paper__arxiv_id",
        "paper__title",
    )
    list_filter = (
        "translation_type",
        "source_language",
        "target_language",
    )


@admin.register(ProcessingJob)
class ProcessingJobAdmin(admin.ModelAdmin):
    list_display = (
        "paper",
        "job_type",
        "status",
        "progress_current",
        "progress_total",
        "created_at",
    )
    search_fields = (
        "paper__arxiv_id",
        "paper__title",
    )
    list_filter = ("job_type", "status")