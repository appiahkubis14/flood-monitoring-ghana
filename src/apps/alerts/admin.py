from django.contrib import admin
from django.contrib.gis.admin import GISModelAdmin

from .models import Alert, AlertRecipient, CommunityReport, FloodEvent, HistoricalFloodRecord


@admin.register(FloodEvent)
class FloodEventAdmin(admin.ModelAdmin):
    list_display = ("flood_zone", "severity", "triggered_by", "started_at", "ended_at", "is_active")
    list_filter = ("severity", "triggered_by", "flood_zone")
    date_hierarchy = "started_at"
    readonly_fields = ("created_at", "updated_at")

    @admin.display(boolean=True, description="Active")
    def is_active(self, obj):
        return obj.is_active


@admin.register(Alert)
class AlertAdmin(admin.ModelAdmin):
    list_display = ("recipient", "severity", "channel", "delivery_status", "sent_at", "created_at")
    list_filter = ("severity", "channel", "delivery_status")
    search_fields = ("recipient__full_name", "recipient__phone_number", "provider_message_id")
    readonly_fields = ("uuid", "created_at", "updated_at")
    date_hierarchy = "created_at"


@admin.register(AlertRecipient)
class AlertRecipientAdmin(admin.ModelAdmin):
    list_display = ("full_name", "phone_number", "preferred_channel", "min_severity", "is_active")
    list_filter = ("preferred_channel", "min_severity", "is_active", "flood_zones")
    search_fields = ("full_name", "phone_number")
    filter_horizontal = ("flood_zones",)


@admin.register(CommunityReport)
class CommunityReportAdmin(GISModelAdmin):
    list_display = ("uuid", "severity", "flood_zone", "is_verified", "created_at")
    list_filter = ("severity", "is_verified", "flood_zone")
    readonly_fields = ("uuid", "created_at", "updated_at")
    date_hierarchy = "created_at"
    actions = ["mark_verified"]
    default_lon = -0.18
    default_lat = 5.60
    default_zoom = 11

    @admin.action(description="Mark selected reports as verified")
    def mark_verified(self, request, queryset):
        from django.utils import timezone
        updated = queryset.update(is_verified=True, verified_by=request.user, verified_at=timezone.now())
        self.message_user(request, f"{updated} report(s) marked as verified.")


@admin.register(HistoricalFloodRecord)
class HistoricalFloodRecordAdmin(admin.ModelAdmin):
    list_display = ("flood_zone", "event_date", "severity", "casualties", "displaced_persons")
    list_filter = ("severity", "flood_zone")
    date_hierarchy = "event_date"
