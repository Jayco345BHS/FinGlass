from core.constants import DEFAULT_FEATURE_SETTINGS
from core.models import AppSetting


def parse_setting_bool(value):
    if isinstance(value, bool):
        return value
    normalized = str(value or "").strip().lower()
    return normalized in {"1", "true", "yes", "on"}


def get_feature_settings(user):
    settings = dict(DEFAULT_FEATURE_SETTINGS)
    rows = AppSetting.objects.filter(user=user, key__startswith="feature.").values("key", "value")
    for row in rows:
        key = str(row.get("key") or "")
        feature = key.removeprefix("feature.")
        if feature in settings:
            settings[feature] = parse_setting_bool(row.get("value"))
    return settings


def update_feature_settings(user, raw_features):
    if not isinstance(raw_features, dict):
        raise ValueError("features object is required")

    current = get_feature_settings(user)

    for feature, value in raw_features.items():
        if feature not in DEFAULT_FEATURE_SETTINGS:
            raise ValueError(f"Unsupported feature: {feature}")
        current[feature] = parse_setting_bool(value)

    for feature, enabled in current.items():
        AppSetting.objects.update_or_create(
            user=user,
            key=f"feature.{feature}",
            defaults={"value": "1" if enabled else "0"},
        )

    return current
