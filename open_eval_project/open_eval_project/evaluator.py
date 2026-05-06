"""Syntax and semantic retention evaluation for multi-hop translation/paraphrase CSV files."""

from __future__ import annotations

import argparse
import json
import math
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

import numpy as np
import pandas as pd
import sacrebleu
import spacy

REQUIRED_COLUMNS = ["model", "group", "source_id", "type", "chain", "EN0", "EN1", "EN2", "EN3"]
ROUND_COLUMNS = [(1, "EN1"), (2, "EN2"), (3, "EN3")]
STOPWORDS = {"the", "a", "an", "of", "in", "on", "at", "to", "for", "by", "with", "and", "or", "but"}
CULTURAL_PATTERNS = [
    r"tempting fate",
    r"save face",
    r"closing the stable door after the horse has bolted",
    r"too good to be true",
    r"pandora'?s box",
    r"putting the cart before the horse",
    r"open a can of worms",
    r"keep their roots alive",
    r"sweep difficult questions under the rug",
    r"have its cake and eat it too",
    r"bury the hatchet",
    r"witch hunt",
]
DATE_WORDS = {
    "yesterday", "today", "tomorrow", "monday", "tuesday", "wednesday", "thursday", "friday", "saturday",
    "sunday", "january", "february", "march", "april", "may", "june", "july", "august", "september",
    "october", "november", "december", "year", "month", "week", "day",
}


@dataclass
class Proposition:
    prop_type: str
    span: str
    extra: dict[str, Any]


class SemanticExtractor:
    """Extracts interpretable proposition-like units with spaCy and a regex fallback."""

    def __init__(self, spacy_model: str = "en_core_web_sm", allow_fallback: bool = True) -> None:
        self.model_name = spacy_model
        self.uses_fallback = False
        try:
            self.nlp = spacy.load(spacy_model)
        except OSError as exc:
            if not allow_fallback:
                raise RuntimeError(
                    f"spaCy model '{spacy_model}' is not installed. Run: python -m spacy download {spacy_model}"
                ) from exc
            self.nlp = spacy.blank("en")
            self.nlp.add_pipe("sentencizer")
            self.uses_fallback = True

    def extract_propositions(self, text: str) -> list[Proposition]:
        if self.uses_fallback:
            return self._extract_regex_propositions(text)
        return self._extract_spacy_propositions(text)

    def extract_entities_and_facts(self, text: str) -> list[str]:
        if self.uses_fallback:
            return extract_regex_entities(text)

        doc = self.nlp(text)
        values: list[str] = []
        seen: set[str] = set()
        labels = {"PERSON", "ORG", "GPE", "LOC", "PRODUCT", "EVENT", "DATE", "TIME", "MONEY", "PERCENT", "QUANTITY", "CARDINAL", "ORDINAL"}
        for ent in doc.ents:
            if ent.label_ in labels:
                key = normalize_text(ent.text)
                if key not in seen:
                    seen.add(key)
                    values.append(ent.text)
        for token in doc:
            if token.like_num:
                key = normalize_text(token.text)
                if key not in seen:
                    seen.add(key)
                    values.append(token.text)
        return values

    def _extract_spacy_propositions(self, text: str) -> list[Proposition]:
        doc = self.nlp(text)
        props: list[Proposition] = []
        seen: set[tuple[str, str]] = set()

        for sent in doc.sents:
            for ent in sent.ents:
                add_prop(props, seen, "entity", ent.text, label=ent.label_)

            for token in sent:
                if token.like_num or token.ent_type_ in {"DATE", "TIME", "MONEY", "PERCENT", "QUANTITY", "CARDINAL", "ORDINAL"}:
                    add_prop(props, seen, "fact", token.text, label=token.ent_type_ or token.pos_)

            for token in sent:
                if token.pos_ not in {"VERB", "AUX"}:
                    continue
                subjects = [child for child in token.children if child.dep_ in {"nsubj", "nsubjpass", "csubj"}]
                objects = [child for child in token.children if child.dep_ in {"dobj", "obj", "pobj", "attr", "dative", "oprd"}]
                complements = [child for child in token.children if child.dep_ in {"ccomp", "xcomp", "acomp"}]
                if subjects or objects or complements:
                    subj = subtree_text(subjects[0]) if subjects else "UNKNOWN"
                    obj_parts = [subtree_text(x) for x in objects + complements]
                    obj = "; ".join(obj_parts) if obj_parts else "UNKNOWN"
                    add_prop(props, seen, "predicate", f"{subj} {token.lemma_} {obj}", subject=subj, verb=token.lemma_, object=obj)

                for child in token.children:
                    if child.dep_ == "neg":
                        add_prop(props, seen, "negation", f"{token.lemma_} negated")

            for token in sent:
                if token.dep_ in {"prep", "agent"}:
                    pobj = [child for child in token.children if child.dep_ in {"pobj", "pcomp"}]
                    if pobj:
                        add_prop(props, seen, "relation", f"{token.head.text} {token.text} {subtree_text(pobj[0])}")

            lowered = sent.text.lower()
            for pattern in CULTURAL_PATTERNS:
                match = re.search(pattern, lowered)
                if match:
                    add_prop(props, seen, "cultural", match.group(0))
        return props

    def _extract_regex_propositions(self, text: str) -> list[Proposition]:
        props: list[Proposition] = []
        seen: set[tuple[str, str]] = set()
        for entity in extract_regex_entities(text):
            words = set(content_words(entity))
            label = "DATE_OR_NUMBER" if any(w in DATE_WORDS or re.match(r"^\d", w) for w in words) else "ENTITY"
            add_prop(props, seen, "entity", entity, label=label)

        for sent in regex_sentences(text):
            words = content_words(sent)
            if words:
                add_prop(props, seen, "sentence_core", " ".join(words[:12]))
            lowered = sent.lower()
            if any(marker in lowered for marker in ["because", "although", "though", "but", "if", "could", "may", "might", "warned", "suggested"]):
                add_prop(props, seen, "relation", " ".join(words[:16]))
            for pattern in CULTURAL_PATTERNS:
                match = re.search(pattern, lowered)
                if match:
                    add_prop(props, seen, "cultural", match.group(0))
        return props


def normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", str(text).lower()).strip()


def content_words(text: str) -> list[str]:
    words = re.findall(r"[a-z]+(?:'[a-z]+)?|\d+(?:\.\d+)?", normalize_text(text))
    return [w for w in words if w not in STOPWORDS]


def regex_sentences(text: str) -> list[str]:
    sentences = re.split(r"(?<=[.!?])\s+(?=[A-Z\"'])", str(text).strip())
    return [s.strip() for s in sentences if s.strip()]


def tokenize_words(text: str) -> list[str]:
    return re.findall(r"[A-Za-z]+(?:'[A-Za-z]+)?", str(text).lower())


def extract_regex_entities(text: str) -> list[str]:
    entities: list[str] = []
    seen: set[str] = set()
    patterns = [
        r"\b(?:[A-Z][a-z]+(?:'s)?)(?:\s+(?:[A-Z][a-z]+|[A-Z]{2,}|of|and|the))*\b",
        r"\b\d+(?:\.\d+)?%?\b",
        r"\b(?:next|last|this)\s+(?:Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday|week|month|year)\b",
        r"\b(?:yesterday|today|tomorrow)\b",
    ]
    for pattern in patterns:
        for match in re.finditer(pattern, str(text)):
            value = match.group(0).strip()
            if value.lower() in STOPWORDS:
                continue
            key = normalize_text(value)
            if key not in seen:
                seen.add(key)
                entities.append(value)
    return entities


def add_prop(props: list[Proposition], seen: set[tuple[str, str]], prop_type: str, span: str, **extra: Any) -> None:
    span = re.sub(r"\s+", " ", str(span).strip())
    if not span:
        return
    key = (prop_type, span.lower())
    if key in seen:
        return
    seen.add(key)
    props.append(Proposition(prop_type, span, extra))


def subtree_text(token: Any) -> str:
    toks = sorted(token.subtree, key=lambda t: t.i)
    return " ".join(t.text for t in toks)


def compute_ttr(text: str) -> float:
    words = tokenize_words(text)
    return round(len(set(words)) / len(words), 4) if words else 0.0


def length_stats(text: str) -> tuple[int, int, int]:
    words = tokenize_words(text)
    sents = regex_sentences(text)
    return len(words), len(str(text)), len(sents)


def structure_similarity(reference: str, hypothesis: str) -> float:
    def features(text: str) -> dict[str, float]:
        sents = regex_sentences(text)
        words = tokenize_words(text)
        word_lens = [len(w) for w in words]
        punct_count = len(re.findall(r"[.,;:!?\-()\"']", str(text)))
        return {
            "sent_count": len(sents),
            "word_count": len(words),
            "avg_word_len": sum(word_lens) / len(word_lens) if word_lens else 0,
            "punct_ratio": punct_count / len(str(text)) if text else 0,
        }

    f1, f2 = features(reference), features(hypothesis)
    sent_sim = minmax_ratio(f1["sent_count"], f2["sent_count"])
    word_sim = minmax_ratio(f1["word_count"], f2["word_count"])
    word_len_sim = 1 - abs(f1["avg_word_len"] - f2["avg_word_len"]) / max(f1["avg_word_len"], f2["avg_word_len"], 1)
    punct_sim = max(0, 1 - abs(f1["punct_ratio"] - f2["punct_ratio"]) / max(f1["punct_ratio"], f2["punct_ratio"], 0.01))
    return round(0.35 * sent_sim + 0.25 * word_sim + 0.25 * word_len_sim + 0.15 * punct_sim, 4)


def minmax_ratio(a: float, b: float) -> float:
    return min(a, b) / max(a, b) if a and b else 0.0


def bounded_ratio_score(ratio: float | None, tolerance: float = 0.5) -> float | None:
    if ratio is None or not math.isfinite(ratio):
        return None
    return round(max(0, 100 * (1 - min(abs(ratio - 1), tolerance) / tolerance)), 4)


def bounded_abs_score(value: float | None, tolerance: float) -> float | None:
    if value is None or not math.isfinite(value):
        return None
    return round(max(0, 100 * (1 - min(abs(value), tolerance) / tolerance)), 4)


def weighted_average(weighted_values: Iterable[tuple[float, float | None]]) -> float | None:
    available = [(w, v) for w, v in weighted_values if v is not None]
    if not available:
        return None
    total_weight = sum(w for w, _ in available)
    return round(sum(w * v for w, v in available) / total_weight, 4)


def syntax_details(reference: str, hypothesis: str) -> dict[str, Any]:
    bleu = sacrebleu.corpus_bleu([hypothesis], [[reference]], tokenize="intl").score
    spbleu = sacrebleu.corpus_bleu([hypothesis], [[reference]], tokenize="13a").score
    chrf = sacrebleu.corpus_chrf([hypothesis], [[reference]]).score
    struct_sim = structure_similarity(reference, hypothesis)

    ttr_ref = compute_ttr(reference)
    ttr_hyp = compute_ttr(hypothesis)
    ttr_drift = round(ttr_hyp - ttr_ref, 4)
    words_ref, chars_ref, sents_ref = length_stats(reference)
    words_hyp, chars_hyp, sents_hyp = length_stats(hypothesis)
    word_ratio = round(words_hyp / words_ref, 4) if words_ref else None
    sent_ratio = round(sents_hyp / sents_ref, 4) if sents_ref else None
    char_ratio = round(chars_hyp / chars_ref, 4) if chars_ref else None
    style_score = weighted_average([
        (0.4, bounded_ratio_score(word_ratio)),
        (0.3, bounded_ratio_score(sent_ratio)),
        (0.3, bounded_abs_score(ttr_drift, 0.3)),
    ])
    syntax_score = weighted_average([(0.35, spbleu), (0.35, chrf), (0.15, struct_sim * 100), (0.15, style_score)])

    return {
        "bleu": round(bleu, 4),
        "spbleu": round(spbleu, 4),
        "chrf": round(chrf, 4),
        "struct_sim": struct_sim,
        "style_score": style_score,
        "syntax_score": syntax_score,
        "ttr_reference": ttr_ref,
        "ttr_hypothesis": ttr_hyp,
        "ttr_drift": ttr_drift,
        "word_count_reference": words_ref,
        "word_count_hypothesis": words_hyp,
        "word_ratio": word_ratio,
        "char_count_reference": chars_ref,
        "char_count_hypothesis": chars_hyp,
        "char_ratio": char_ratio,
        "sent_count_reference": sents_ref,
        "sent_count_hypothesis": sents_hyp,
        "sent_ratio": sent_ratio,
    }


def match_proposition(prop: Proposition, target_text: str) -> str:
    target = normalize_text(target_text)
    span = normalize_text(prop.span)
    if not span:
        return "deleted"
    if span in target:
        return "retained"
    words = content_words(span)
    if not words:
        return "deleted"
    if prop.prop_type == "entity":
        if all(w in target for w in words):
            return "retained"
        if any(w in target for w in words):
            return "generalized"
        return "deleted"
    matched = sum(1 for w in words if w in target)
    ratio = matched / len(words)
    if ratio >= 0.8:
        return "retained"
    if ratio >= 0.5:
        return "generalized"
    return "deleted"


def retention_rate(items: list[str], target_text: str) -> tuple[float | None, int, int]:
    if not items:
        return None, 0, 0
    target = normalize_text(target_text)
    retained = 0
    for item in items:
        words = content_words(item)
        if normalize_text(item) in target or (words and all(w in target for w in words)):
            retained += 1
    return round(retained / len(items), 4), retained, len(items)


def cultural_retention(reference: str, hypothesis: str) -> tuple[float | None, int, int]:
    ref = normalize_text(reference)
    hyp = normalize_text(hypothesis)
    found: list[str] = []
    for pattern in CULTURAL_PATTERNS:
        match = re.search(pattern, ref)
        if match:
            found.append(match.group(0))
    if not found:
        return None, 0, 0
    retained = 0
    for item in found:
        words = content_words(item)
        if item in hyp or (words and sum(w in hyp for w in words) / len(words) >= 0.5):
            retained += 1
    return round(retained / len(found), 4), retained, len(found)


def semantic_details(reference: str, hypothesis: str, extractor: SemanticExtractor) -> dict[str, Any]:
    props = extractor.extract_propositions(reference)
    counts = {"retained": 0, "generalized": 0, "mistranslated": 0, "deleted": 0}
    details: list[dict[str, str]] = []
    for prop in props:
        status = match_proposition(prop, hypothesis)
        counts[status] += 1
        details.append({"type": prop.prop_type, "span": prop.span, "status": status})

    prop_total = len(props)
    if prop_total:
        prop_retained_rate = round(counts["retained"] / prop_total, 4)
        prop_generalized_rate = round(counts["generalized"] / prop_total, 4)
        prop_lost_rate = round((counts["mistranslated"] + counts["deleted"]) / prop_total, 4)
        prop_score = round(100 * (counts["retained"] + 0.5 * counts["generalized"]) / prop_total, 4)
    else:
        prop_retained_rate = prop_generalized_rate = prop_lost_rate = prop_score = None

    entities = extractor.extract_entities_and_facts(reference)
    entity_rate, entity_retained, entity_total = retention_rate(entities, hypothesis)
    entity_score = round(entity_rate * 100, 4) if entity_rate is not None else None
    cultural_rate, cultural_retained, cultural_total = cultural_retention(reference, hypothesis)
    cultural_score = round(cultural_rate * 100, 4) if cultural_rate is not None else None
    semantic_score = weighted_average([
        (0.70 if cultural_score is not None else 0.80, prop_score),
        (0.20, entity_score),
        (0.10, cultural_score),
    ])

    return {
        "prop_total": prop_total,
        "prop_retained": counts["retained"],
        "prop_generalized": counts["generalized"],
        "prop_mistranslated": counts["mistranslated"],
        "prop_deleted": counts["deleted"],
        "prop_retained_rate": prop_retained_rate,
        "prop_generalized_rate": prop_generalized_rate,
        "prop_lost_rate": prop_lost_rate,
        "prop_score": prop_score,
        "entity_total": entity_total,
        "entity_retained": entity_retained,
        "entity_retained_rate": entity_rate,
        "entity_score": entity_score,
        "cultural_total": cultural_total,
        "cultural_retained": cultural_retained,
        "cultural_retained_rate": cultural_rate,
        "cultural_score": cultural_score,
        "semantic_score": semantic_score,
        "proposition_details_json": json.dumps(details, ensure_ascii=False),
        "spacy_model": extractor.model_name,
        "semantic_fallback_used": extractor.uses_fallback,
    }


def validate_input(df: pd.DataFrame) -> None:
    missing = [col for col in REQUIRED_COLUMNS if col not in df.columns]
    if missing:
        raise ValueError(f"Input CSV is missing required columns: {missing}")


def evaluate_dataframe(df: pd.DataFrame, final_only: bool = True, spacy_model: str = "en_core_web_sm", allow_fallback: bool = True) -> pd.DataFrame:
    validate_input(df)
    extractor = SemanticExtractor(spacy_model=spacy_model, allow_fallback=allow_fallback)
    round_cols = [(3, "EN3")] if final_only else ROUND_COLUMNS
    rows: list[dict[str, Any]] = []

    for _, input_row in df.iterrows():
        reference = str(input_row.get("EN0") or "").strip()
        if not reference:
            continue
        for round_id, hyp_col in round_cols:
            hypothesis = str(input_row.get(hyp_col) or "").strip()
            if not hypothesis:
                continue
            base = {
                "model": input_row.get("model", ""),
                "group": input_row.get("group", ""),
                "source_id": input_row.get("source_id", ""),
                "type": input_row.get("type", ""),
                "chain": input_row.get("chain", ""),
                "round": round_id,
                "reference_col": "EN0",
                "hypothesis_col": hyp_col,
            }
            rows.append({**base, **syntax_details(reference, hypothesis), **semantic_details(reference, hypothesis, extractor)})
    return pd.DataFrame(rows)


def write_outputs(scores: pd.DataFrame, output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    scores.to_csv(output_dir / "scores_detailed.csv", index=False)

    compact_cols = [
        "model", "group", "source_id", "type", "chain", "round", "syntax_score", "semantic_score",
        "spbleu", "chrf", "prop_score", "entity_score", "cultural_score",
    ]
    scores[[c for c in compact_cols if c in scores.columns]].to_csv(output_dir / "scores.csv", index=False)

    if len(scores):
        summary = scores.groupby("model", dropna=False).agg(
            n_samples=("source_id", "count"),
            syntax_score_mean=("syntax_score", "mean"),
            syntax_score_std=("syntax_score", "std"),
            semantic_score_mean=("semantic_score", "mean"),
            semantic_score_std=("semantic_score", "std"),
            spbleu_mean=("spbleu", "mean"),
            chrf_mean=("chrf", "mean"),
            prop_score_mean=("prop_score", "mean"),
            entity_score_mean=("entity_score", "mean"),
        ).reset_index()
        summary = summary.sort_values(["semantic_score_mean", "syntax_score_mean"], ascending=[False, False])
        summary.to_csv(output_dir / "summary_by_model.csv", index=False)

        by_chain = scores.groupby(["model", "chain"], dropna=False).agg(
            n_samples=("source_id", "count"),
            syntax_score_mean=("syntax_score", "mean"),
            semantic_score_mean=("semantic_score", "mean"),
        ).reset_index()
        by_chain.to_csv(output_dir / "summary_by_model_chain.csv", index=False)


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate syntax and semantic retention for a fixed multi-hop CSV format.")
    parser.add_argument("--input", required=True, help="Input CSV with model/group/source_id/type/chain/EN0/EN1/EN2/EN3 columns.")
    parser.add_argument("--output-dir", default="outputs", help="Directory for output CSV files.")
    parser.add_argument("--all-rounds", action="store_true", help="Evaluate EN1, EN2, and EN3 against EN0 instead of only EN3.")
    parser.add_argument("--spacy-model", default="en_core_web_sm", help="spaCy model name used for semantic extraction.")
    parser.add_argument("--no-fallback", action="store_true", help="Fail if the spaCy model is unavailable instead of using regex fallback.")
    args = parser.parse_args()

    df = pd.read_csv(args.input)
    scores = evaluate_dataframe(df, final_only=not args.all_rounds, spacy_model=args.spacy_model, allow_fallback=not args.no_fallback)
    write_outputs(scores, Path(args.output_dir))

    print(f"Wrote {len(scores)} evaluated rows to {args.output_dir}")
    if "semantic_fallback_used" in scores.columns and scores["semantic_fallback_used"].any():
        print("Warning: semantic regex fallback was used because the requested spaCy model was not available.")
    if len(scores):
        print(scores[["syntax_score", "semantic_score"]].mean(numeric_only=True).round(4).to_string())


if __name__ == "__main__":
    main()
