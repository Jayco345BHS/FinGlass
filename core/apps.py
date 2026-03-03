from django.apps import AppConfig


class CoreConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "core"
    label = "core"

    def ready(self):
        """Customize Django admin site branding."""
        from django.contrib import admin
        admin.site.site_header = "FinGlass Administration"
        admin.site.site_title = "FinGlass Admin"
        admin.site.index_title = "Welcome to FinGlass Admin"
