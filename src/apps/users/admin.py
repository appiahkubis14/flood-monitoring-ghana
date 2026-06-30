from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as DjangoUserAdmin

from .models import User


@admin.register(User)
class UserAdmin(DjangoUserAdmin):
    """Extends Django's built-in UserAdmin with FloodWatch-specific fields."""

    list_display = ("username", "full_name_display", "role", "phone_number", "is_active", "date_joined")
    list_filter = ("role", "is_active", "receives_whatsapp_alerts", "receives_sms_alerts")
    search_fields = ("username", "first_name", "last_name", "email", "phone_number")
    fieldsets = DjangoUserAdmin.fieldsets + (
        (
            "FloodWatch Profile",
            {
                "fields": (
                    "role",
                    "phone_number",
                    "preferred_language",
                    "organization",
                    "receives_whatsapp_alerts",
                    "receives_sms_alerts",
                )
            },
        ),
    )

    @admin.display(description="Full name")
    def full_name_display(self, obj):
        return obj.get_full_name() or "—"
