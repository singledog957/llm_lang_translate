# Section: SYSTEM_PROMPT
You are an extremely strict professional translation quality evaluator specializing in cross-lingual pragmatic analysis. You must return only valid JSON with no additional explanation or commentary. Apply severe standards: any subtle semantic loss, register drift, or pragmatic shift should result in significant deductions.

# Section: USER_PREAMBLE
Evaluate the pragmatic quality of the following translations. For each item, an English source text (EN0) has been translated through a multi-language chain and back to English (EN_last). Assess how well the pragmatic features are preserved.

For EACH source_id, return a JSON object with exactly 5 dimension keys: "irony", "speech_act", "register", "uncertainty", "attitude". Each maps to a compact detail object with integer-valued fields as defined below.

---

## Dimension 1: Irony & Implication (key: "irony")

Fields and allowed values:
- iron_has: Source contains irony/sarcasm? [1=yes, 0=no]
- iron_kept: Irony preserved in EN_last? [2=fully, 1=partially, 0=lost] — use 2 if iron_has=0
- iron_loss: Severity of irony loss [0=none, 1=minor, 2=moderate, 3=severe]
- impl_has: Source contains implicit/indirect meaning beyond literal? [1=yes, 0=no]
- impl_kept: Implicit meaning preserved? [2=fully, 1=partially, 0=lost] — use 2 if impl_has=0
- impl_literal: Does literal translation override deeper meaning? [0=no, 1=slightly, 2=clearly]

## Dimension 2: Speech Act Maintenance (key: "speech_act")

Fields and allowed values:
- sa_type: Primary speech act [0=statement, 1=request, 2=suggestion, 3=refusal, 4=promise, 5=question]
- sa_kept: Same speech act performed in EN_last? [2=fully, 1=partially, 0=lost]
- sa_shift: Functional shift present? (e.g., request→statement) [0=none, 1=minor, 2=severe]
- sa_indirect: Indirect speech act preserved? [2=preserved, 1=partially, 0=made direct]
- sa_polite: Politeness strategy serves the speech act goal? [1=yes, 0=no]
- sa_force: Illocutionary force preserved? [2=preserved, 1=weakened, 0=lost]

## Dimension 3: Politeness & Register Drift (key: "register")

Fields and allowed values:
- reg_src: Source register level [0=informal, 1=neutral, 2=formal, 3=highly formal]
- reg_match: EN_last register matches source? [2=matches, 1=minor drift, 0=significant drift]
- pol_dir: Politeness drift direction [0=no drift, 1=more formal, -1=more casual]
- pol_face: Face-saving/face-threatening acts preserved? [2=preserved, 1=partially, 0=lost]
- pol_power: Implied power distance/social relationship preserved? [2=preserved, 1=blurred, 0=reversed or lost]
- pol_excess: Over- or under-politeness present? [0=none, 1=slightly over, 2=severely over, -1=under-polite]

## Dimension 4: Uncertainty Preservation (key: "uncertainty")

Fields and allowed values:
- unc_has: Source contains uncertainty expression? [1=yes, 0=no]
- unc_type: Uncertainty type [0=none, 1=epistemic(I think/maybe), 2=deontic(should/ought), 3=emotional(worry/hope)]
- unc_kept: Uncertainty preserved in EN_last? [2=fully, 1=partially, 0=lost/made certain] — use 2 if unc_has=0
- unc_shift: Degree of uncertainty changed? [0=accurate, 1=reduced, 2=amplified, 3=reversed to certainty]
- unc_modal: Modal verbs/hedging particles correctly translated? [2=correct, 1=approximate, 0=wrong or omitted]
- unc_hedge: Hedging expressions (I think, perhaps, it seems) preserved? [2=preserved, 1=weakened, 0=lost]

## Dimension 5: Attitudinal Intensity (key: "attitude")

Fields and allowed values:
- att_polar: Source emotional polarity [-2=strongly negative, -1=mildly negative, 0=neutral, 1=mildly positive, 2=strongly positive]
- att_polar_kept: Same polarity preserved in EN_last? [2=fully, 1=partially, 0=reversed or lost]
- att_intensity: Emotional intensity changed? [0=unchanged, 1=weakened, 2=severely weakened, 3=amplified]
- att_lexical: Evaluative/emotional words correctly translated? [2=accurate, 1=approximate, 0=wrong replacement]
- att_gradual: Gradual emotional build-up/escalation preserved? [2=preserved, 1=partially, 0=flattened]
- att_neutral: Neutralization/flattening tendency present? [0=none, 1=slight, 2=clear]

---

## Required Output Format

Return a single JSON object. Top-level keys are source_ids. Each maps to an object with exactly the 5 dimension keys, each with the compact detail object.

Example:
```json
{
  "EN-1": {
    "irony": {"iron_has": 1, "iron_kept": 1, "iron_loss": 2, "impl_has": 0, "impl_kept": 2, "impl_literal": 0},
    "speech_act": {"sa_type": 1, "sa_kept": 2, "sa_shift": 0, "sa_indirect": 2, "sa_polite": 1, "sa_force": 2},
    "register": {"reg_src": 1, "reg_match": 1, "pol_dir": 1, "pol_face": 2, "pol_power": 2, "pol_excess": 0},
    "uncertainty": {"unc_has": 1, "unc_type": 1, "unc_kept": 2, "unc_shift": 0, "unc_modal": 2, "unc_hedge": 1},
    "attitude": {"att_polar": -1, "att_polar_kept": 2, "att_intensity": 1, "att_lexical": 2, "att_gradual": 2, "att_neutral": 0}
  }
}
```

Texts to evaluate:

# Section: KEY_SCHEMA_DOCS
This section is for human reference only and is not parsed by code.

### Scoring Rules (applied by code, not LLM)

**irony** (start 100, deduct):
- iron_has=1 & iron_kept=0 → -30; iron_kept=1 → -15
- iron_loss=3 → -10; iron_loss=2 → -5
- impl_has=1 & impl_kept=0 → -25; impl_kept=1 → -12
- impl_literal=2 → -10; impl_literal=1 → -5
- If iron_has=0 AND impl_has=0 → full score (100)

**speech_act** (start 100, deduct):
- sa_kept=0 → -35; sa_kept=1 → -15
- sa_shift=2 → -20; sa_shift=1 → -8
- sa_indirect=0 → -15; sa_indirect=1 → -7
- sa_force=0 → -15; sa_force=1 → -7

**register** (start 100, deduct):
- reg_match=0 → -30; reg_match=1 → -10
- pol_face=0 → -20; pol_face=1 → -8
- pol_power=0 → -20; pol_power=1 → -8
- pol_excess=±1 → -5; pol_excess=2 or -1(severe) → -15

**uncertainty** (start 100, deduct):
- If unc_has=0 → full score (100)
- unc_kept=0 → -35; unc_kept=1 → -15
- unc_shift=3 → -20; unc_shift=1 or 2 → -8
- unc_modal=0 → -15; unc_modal=1 → -5
- unc_hedge=0 → -10; unc_hedge=1 → -4

**attitude** (start 100, deduct):
- att_polar_kept=0 → -35; att_polar_kept=1 → -15
- att_intensity=2 → -15; att_intensity=1 → -7; att_intensity=3 → -10
- att_lexical=0 → -15; att_lexical=1 → -5
- att_gradual=0 → -10; att_gradual=1 → -5
- att_neutral=2 → -10; att_neutral=1 → -4
