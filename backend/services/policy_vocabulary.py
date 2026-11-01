"""Shared policy vocabulary for the API, discovery protocol and synthetic verifiers."""
from typing import Any, Dict

CORE_USAGE_KEYS = [
    "ads_brand",
    "ads_political",
    "ads_psa",
    "film_tv",
    "streaming_visual",
    "video_game",
    "podcast_audio",
    "ugc_creator",
    "live_performance",
    "background_music",
    "corporate_internal",
    "educational",
    "personal_noncommercial",
    "ai_training_recursive",
    "derivative_remix",
]

AI_USAGE_KEYS = [
    "ai_model_training",
    "ai_model_fine_tuning",
    "ai_grounded_generation",
    "ai_embedding_creation",
    "ai_embedding_retrieval",
    "ai_source_separation",
    "ai_music_transformation",
    "ai_lyric_analysis",
    "ai_lyric_generation",
    "ai_synthetic_voice",
]

USAGE_KEYS = CORE_USAGE_KEYS + AI_USAGE_KEYS

AI_INPUT_KEYS = [
    "full_mix",
    "stems",
    "isolated_vocals",
    "lyrics",
    "composition_data",
    "reference_embeddings",
]

AI_MODEL_SCOPE_KEYS = [
    "private_single_tenant",
    "shared_commercial_model",
    "public_or_open_weights",
]

AI_LIMIT_KEYS = [
    "maxSourceDurationSeconds",
    "maxOutputDurationSeconds",
    "maxLyricCharacters",
    "sourceRetentionDays",
    "embeddingRetentionDays",
]

AI_SAFEGUARD_KEYS = [
    "provenanceReceipt",
    "outputWatermark",
    "attribution",
    "similarityReview",
    "deletionAttestation",
]

RESTRICTION_KEYS = [
    "political",
    "adult",
    "alcohol_tobacco_cannabis",
    "weapons_defense",
    "gambling",
    "religion",
    "sensitive_social_issues",
    "health_pharma",
    "children_sensitive",
    "likeness_voice_clone",
    "deceptive_endorsement",
]


def default_ai_policy(preset: str = "review_each_ai_use") -> Dict[str, Any]:
    review = preset == "review_each_ai_use"
    input_state = "requires_approval" if review else "blocked"
    return {
        "schemaVersion": "clef.ai-policy.v1",
        "inputs": {key: input_state for key in AI_INPUT_KEYS},
        "modelScopes": {
            "private_single_tenant": input_state,
            "shared_commercial_model": input_state,
            "public_or_open_weights": "blocked",
        },
        # null means the value must be settled in the individual license. It never means unlimited.
        "limits": {key: None for key in AI_LIMIT_KEYS},
        "safeguards": {key: True for key in AI_SAFEGUARD_KEYS},
    }

