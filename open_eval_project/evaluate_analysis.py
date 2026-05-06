from __future__ import annotations

import pandas as pd

SCORE_METRICS = ["irony", "speech_act", "register", "uncertainty", "attitude"]

METRIC_DISPLAY = {
    "irony": "Irony & Implication",
    "speech_act": "Speech Act Maintenance",
    "register": "Politeness & Register Drift",
    "uncertainty": "Uncertainty Preservation",
    "attitude": "Attitudinal Intensity",
}

LEGACY_MAPPING = {
    "\u8bbd\u523a\u3001\u6697\u793a\u3001\u95f4\u63a5\u610f\u4e49\u662f\u5426\u4fdd\u7559": "irony",
    "\u8bf7\u6c42\u3001\u5efa\u8bae\u3001\u62d2\u7edd\u7b49\u529f\u80fd\u662f\u5426\u4fdd\u6301": "speech_act",
    "\u793c\u8c8c\u7a0b\u5ea6\u3001\u8bed\u57df\u3001\u8eab\u4efd\u5173\u7cfb\u662f\u5426\u6f02\u79fb": "register",
    "\u4e0d\u786e\u5b9a\u6027\u8868\u8fbe\u662f\u5426\u4fdd\u7559": "uncertainty",
    "\u6001\u5ea6\u5f3a\u5ea6\u662f\u5426\u6539\u53d8": "attitude",
}


def compute_irony_score(values: dict) -> int:
    """Dimension 1: Irony & Implication Preservation. Returns 0-100."""
    iron_has = values.get("iron_has", 0)
    impl_has = values.get("impl_has", 0)

    if not iron_has and not impl_has:
        return 100

    score = 100

    if iron_has:
        iron_kept = values.get("iron_kept", 2)
        iron_loss = values.get("iron_loss", 0)
        if iron_kept == 0:
            score -= 30
        elif iron_kept == 1:
            score -= 15
        if iron_loss == 3:
            score -= 10
        elif iron_loss == 2:
            score -= 5

    if impl_has:
        impl_kept = values.get("impl_kept", 2)
        impl_literal = values.get("impl_literal", 0)
        if impl_kept == 0:
            score -= 25
        elif impl_kept == 1:
            score -= 12
        if impl_literal == 2:
            score -= 10
        elif impl_literal == 1:
            score -= 5

    return max(0, score)


def compute_speech_act_score(values: dict) -> int:
    """Dimension 2: Speech Act Maintenance. Returns 0-100."""
    score = 100

    sa_kept = values.get("sa_kept", 2)
    if sa_kept == 0:
        score -= 35
    elif sa_kept == 1:
        score -= 15

    sa_shift = values.get("sa_shift", 0)
    if sa_shift == 2:
        score -= 20
    elif sa_shift == 1:
        score -= 8

    sa_indirect = values.get("sa_indirect", 2)
    if sa_indirect == 0:
        score -= 15
    elif sa_indirect == 1:
        score -= 7

    sa_force = values.get("sa_force", 2)
    if sa_force == 0:
        score -= 15
    elif sa_force == 1:
        score -= 7

    return max(0, score)


def compute_register_score(values: dict) -> int:
    """Dimension 3: Politeness & Register Drift. Returns 0-100."""
    score = 100

    reg_match = values.get("reg_match", 2)
    if reg_match == 0:
        score -= 30
    elif reg_match == 1:
        score -= 10

    pol_face = values.get("pol_face", 2)
    if pol_face == 0:
        score -= 20
    elif pol_face == 1:
        score -= 8

    pol_power = values.get("pol_power", 2)
    if pol_power == 0:
        score -= 20
    elif pol_power == 1:
        score -= 8

    pol_excess = values.get("pol_excess", 0)
    if pol_excess in (2, -1):
        score -= 15
    elif pol_excess == 1:
        score -= 5

    return max(0, score)


def compute_uncertainty_score(values: dict) -> int:
    """Dimension 4: Uncertainty Preservation. Returns 0-100."""
    unc_has = values.get("unc_has", 0)

    if not unc_has:
        return 100

    score = 100

    unc_kept = values.get("unc_kept", 2)
    if unc_kept == 0:
        score -= 35
    elif unc_kept == 1:
        score -= 15

    unc_shift = values.get("unc_shift", 0)
    if unc_shift == 3:
        score -= 20
    elif unc_shift in (1, 2):
        score -= 8

    unc_modal = values.get("unc_modal", 2)
    if unc_modal == 0:
        score -= 15
    elif unc_modal == 1:
        score -= 5

    unc_hedge = values.get("unc_hedge", 2)
    if unc_hedge == 0:
        score -= 10
    elif unc_hedge == 1:
        score -= 4

    return max(0, score)


def compute_attitude_score(values: dict) -> int:
    """Dimension 5: Attitudinal Intensity. Returns 0-100."""
    score = 100

    att_polar_kept = values.get("att_polar_kept", 2)
    if att_polar_kept == 0:
        score -= 35
    elif att_polar_kept == 1:
        score -= 15

    att_intensity = values.get("att_intensity", 0)
    if att_intensity == 2:
        score -= 15
    elif att_intensity == 1:
        score -= 7
    elif att_intensity == 3:
        score -= 10

    att_lexical = values.get("att_lexical", 2)
    if att_lexical == 0:
        score -= 15
    elif att_lexical == 1:
        score -= 5

    att_gradual = values.get("att_gradual", 2)
    if att_gradual == 0:
        score -= 10
    elif att_gradual == 1:
        score -= 5

    att_neutral = values.get("att_neutral", 0)
    if att_neutral == 2:
        score -= 10
    elif att_neutral == 1:
        score -= 4

    return max(0, score)


def compute_dim_scores(raw_dimensions: dict) -> dict:
    """Map compact raw dimensions to the 5 score columns."""
    return {
        "irony": compute_irony_score(raw_dimensions.get("irony", {})),
        "speech_act": compute_speech_act_score(raw_dimensions.get("speech_act", {})),
        "register": compute_register_score(raw_dimensions.get("register", {})),
        "uncertainty": compute_uncertainty_score(raw_dimensions.get("uncertainty", {})),
        "attitude": compute_attitude_score(raw_dimensions.get("attitude", {})),
    }


def prepare_scores_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    """Normalize legacy score columns and compute average_score."""
    normalized = df.copy()

    for old_col, new_col in LEGACY_MAPPING.items():
        if old_col in normalized.columns and new_col not in normalized.columns:
            normalized[new_col] = normalized[old_col]

    for metric in SCORE_METRICS:
        if metric in normalized.columns:
            normalized[metric] = pd.to_numeric(normalized[metric], errors="coerce")
        else:
            normalized[metric] = float("nan")

    normalized = normalized.dropna(subset=SCORE_METRICS, how="all")
    if not normalized.empty:
        normalized["average_score"] = normalized[SCORE_METRICS].mean(axis=1)

    return normalized
