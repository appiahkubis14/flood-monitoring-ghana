"""
Custom user model for FloodWatch Ghana.

A custom user model is used from day one (rather than the default
``auth.User``) because alert delivery needs phone-number-based identity
(WhatsApp/SMS) and role-based permissions (admin / field officer / community
member) that don't fit Django's default user model cleanly, and swapping the
user model later is a painful migration.
"""
from __future__ import annotations

from django.contrib.auth.models import AbstractUser
from django.db import models

from apps.core.models import TimeStampedModel


class UserRole(models.TextChoices):
    ADMIN = "admin", "Administrator"
    FIELD_OFFICER = "field_officer", "Field Officer"
    COMMUNITY = "community", "Community Member"


class User(AbstractUser, TimeStampedModel):
    """Extends AbstractUser with phone number, role, and alert preferences.

    ``phone_number`` is the canonical contact channel for WhatsApp/SMS
    alerts and is stored in E.164 format (e.g. ``+233241234567``).
    """

    role = models.CharField(
        max_length=20, choices=UserRole.choices, default=UserRole.COMMUNITY, db_index=True
    )
    phone_number = models.CharField(
        max_length=20,
        blank=True,
        db_index=True,
        help_text="E.164 format, e.g. +233241234567",
    )
    preferred_language = models.CharField(
        max_length=10,
        choices=[("en", "English"), ("tw", "Twi")],
        default="en",
    )
    receives_whatsapp_alerts = models.BooleanField(default=True)
    receives_sms_alerts = models.BooleanField(default=False)
    organization = models.CharField(max_length=150, blank=True)

    class Meta:
        ordering = ["-date_joined"]
        verbose_name = "User"
        verbose_name_plural = "Users"

    def __str__(self) -> str:
        return self.get_full_name() or self.username

    @property
    def is_admin(self) -> bool:
        return self.role == UserRole.ADMIN or self.is_superuser

    @property
    def is_field_officer(self) -> bool:
        return self.role == UserRole.FIELD_OFFICER
