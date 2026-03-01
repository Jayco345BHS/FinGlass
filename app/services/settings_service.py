from ..constants import DEFAULT_FEATURE_SETTINGS


def parse_setting_bool(value):
    if isinstance(value, bool):
        return value
    normalized = str(value or "").strip().lower()
    return normalized in {"1", "true", "yes", "on"}


def get_feature_settings(db, user_id):
    settings = dict(DEFAULT_FEATURE_SETTINGS)
    rows = db.execute(
        """
        SELECT key, value
        FROM app_settings
        WHERE user_id = ?
          AND key LIKE 'feature.%'
        """,
        (user_id,),
    ).fetchall()
    for row in rows:
        key = str(row["key"] or "")
        feature = key.removeprefix("feature.")
        if feature in settings:
            settings[feature] = parse_setting_bool(row["value"])
    return settings


def update_feature_settings(db, user_id, raw_features):
    if not isinstance(raw_features, dict):
        raise ValueError("features object is required")

    current = get_feature_settings(db, user_id)

    for feature, value in raw_features.items():
        if feature not in DEFAULT_FEATURE_SETTINGS:
            raise ValueError(f"Unsupported feature: {feature}")
        current[feature] = parse_setting_bool(value)

    for feature, enabled in current.items():
        db.execute(
            """
            INSERT INTO app_settings (user_id, key, value, updated_at)
            VALUES (?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(user_id, key) DO UPDATE SET
                value = excluded.value,
                updated_at = CURRENT_TIMESTAMP
            """,
            (user_id, f"feature.{feature}", "1" if enabled else "0"),
        )

    db.commit()
    return current
