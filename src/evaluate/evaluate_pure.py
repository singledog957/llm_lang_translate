import os
import sys
import json
import time
import logging
import glob
from concurrent.futures import ThreadPoolExecutor, as_completed
from tqdm import tqdm

# Add project root to sys.path
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from dotenv import load_dotenv
from src.api_client import APIClient, ChatMessage

logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')

# Load configuration
load_dotenv()

# ================= Configuration =================
ITEMS_PER_REQUEST = 4       # N texts per request
CONCURRENT_REQUESTS = 3     # M concurrent requests
EVAL_MODEL = "gpt-5.5"      # Model used for evaluation
# =================================================

BASE_URL = os.environ.get("BASE_URL", "https://www.packyapi.com/v1")
API_KEY  = os.environ.get("API_KEY", "sk-6s7eF1YA8B35EiJkaX188UIr3LiJtk8LXK32MVIDy3AXfB1E")
BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# =================== Prompt Loading ===================

def load_eval_prompt() -> dict:
    """Load and parse evaluation prompt sections from 1_data/prompts/eval_prompt.md.
    Returns a dict keyed by section name (e.g. 'SYSTEM_PROMPT', 'USER_PREAMBLE').
    """
    prompt_file = os.path.join(BASE_DIR, "1_data", "prompts", "eval_prompt.md")
    with open(prompt_file, 'r', encoding='utf-8') as f:
        content = f.read()

    sections: dict = {}
    current_section = None
    current_lines: list = []

    for line in content.split('\n'):
        if line.startswith('# Section: '):
            if current_section is not None:
                sections[current_section] = '\n'.join(current_lines).strip()
            current_section = line[len('# Section: '):].strip()
            current_lines = []
        else:
            current_lines.append(line)

    if current_section is not None:
        sections[current_section] = '\n'.join(current_lines).strip()

    return sections


# =================== Score Computation ===================

def compute_irony_score(d: dict) -> int:
    """Dimension 1: Irony & Implication Preservation. Returns 0-100.
    If source has neither irony nor implication, full score (100).
    """
    iron_has = d.get('iron_has', 0)
    impl_has = d.get('impl_has', 0)

    if not iron_has and not impl_has:
        return 100

    score = 100

    if iron_has:
        iron_kept = d.get('iron_kept', 2)
        iron_loss = d.get('iron_loss', 0)
        if iron_kept == 0:
            score -= 30
        elif iron_kept == 1:
            score -= 15
        if iron_loss == 3:
            score -= 10
        elif iron_loss == 2:
            score -= 5

    if impl_has:
        impl_kept = d.get('impl_kept', 2)
        impl_literal = d.get('impl_literal', 0)
        if impl_kept == 0:
            score -= 25
        elif impl_kept == 1:
            score -= 12
        if impl_literal == 2:
            score -= 10
        elif impl_literal == 1:
            score -= 5

    return max(0, score)


def compute_speech_act_score(d: dict) -> int:
    """Dimension 2: Speech Act Maintenance. Returns 0-100."""
    score = 100

    sa_kept = d.get('sa_kept', 2)
    if sa_kept == 0:
        score -= 35
    elif sa_kept == 1:
        score -= 15

    sa_shift = d.get('sa_shift', 0)
    if sa_shift == 2:
        score -= 20
    elif sa_shift == 1:
        score -= 8

    sa_indirect = d.get('sa_indirect', 2)
    if sa_indirect == 0:
        score -= 15
    elif sa_indirect == 1:
        score -= 7

    sa_force = d.get('sa_force', 2)
    if sa_force == 0:
        score -= 15
    elif sa_force == 1:
        score -= 7

    return max(0, score)


def compute_register_score(d: dict) -> int:
    """Dimension 3: Politeness & Register Drift. Returns 0-100."""
    score = 100

    reg_match = d.get('reg_match', 2)
    if reg_match == 0:
        score -= 30
    elif reg_match == 1:
        score -= 10

    pol_face = d.get('pol_face', 2)
    if pol_face == 0:
        score -= 20
    elif pol_face == 1:
        score -= 8

    pol_power = d.get('pol_power', 2)
    if pol_power == 0:
        score -= 20
    elif pol_power == 1:
        score -= 8

    pol_excess = d.get('pol_excess', 0)
    if pol_excess in (2, -1):   # severely over-polite OR under-polite
        score -= 15
    elif pol_excess == 1:       # slightly over-polite
        score -= 5

    return max(0, score)


def compute_uncertainty_score(d: dict) -> int:
    """Dimension 4: Uncertainty Preservation. Returns 0-100.
    If source has no uncertainty expression, full score (100).
    """
    unc_has = d.get('unc_has', 0)

    if not unc_has:
        return 100

    score = 100

    unc_kept = d.get('unc_kept', 2)
    if unc_kept == 0:
        score -= 35
    elif unc_kept == 1:
        score -= 15

    unc_shift = d.get('unc_shift', 0)
    if unc_shift == 3:
        score -= 20
    elif unc_shift in (1, 2):
        score -= 8

    unc_modal = d.get('unc_modal', 2)
    if unc_modal == 0:
        score -= 15
    elif unc_modal == 1:
        score -= 5

    unc_hedge = d.get('unc_hedge', 2)
    if unc_hedge == 0:
        score -= 10
    elif unc_hedge == 1:
        score -= 4

    return max(0, score)


def compute_attitude_score(d: dict) -> int:
    """Dimension 5: Attitudinal Intensity. Returns 0-100."""
    score = 100

    att_polar_kept = d.get('att_polar_kept', 2)
    if att_polar_kept == 0:
        score -= 35
    elif att_polar_kept == 1:
        score -= 15

    att_intensity = d.get('att_intensity', 0)
    if att_intensity == 2:
        score -= 15
    elif att_intensity == 1:
        score -= 7
    elif att_intensity == 3:
        score -= 10

    att_lexical = d.get('att_lexical', 2)
    if att_lexical == 0:
        score -= 15
    elif att_lexical == 1:
        score -= 5

    att_gradual = d.get('att_gradual', 2)
    if att_gradual == 0:
        score -= 10
    elif att_gradual == 1:
        score -= 5

    att_neutral = d.get('att_neutral', 0)
    if att_neutral == 2:
        score -= 10
    elif att_neutral == 1:
        score -= 4

    return max(0, score)


def compute_dim_scores(raw_dimensions: dict) -> dict:
    """Map LLM compact keys → 5 dimension scores (0-100 each)."""
    return {
        "irony":       compute_irony_score(raw_dimensions.get('irony', {})),
        "speech_act":  compute_speech_act_score(raw_dimensions.get('speech_act', {})),
        "register":    compute_register_score(raw_dimensions.get('register', {})),
        "uncertainty": compute_uncertainty_score(raw_dimensions.get('uncertainty', {})),
        "attitude":    compute_attitude_score(raw_dimensions.get('attitude', {})),
    }


# =================== Data Extraction ===================

def extract_data_from_jsonl(file_path: str) -> list:
    """Extract items to evaluate. Only EN0 and the final back-translated EN."""
    data = []
    with open(file_path, 'r', encoding='utf-8') as f:
        for line in f:
            if not line.strip():
                continue
            item = json.loads(line)

            texts = item.get("texts", {})
            en_keys = [k for k in texts.keys() if k.startswith("EN")]
            en_indices = [int(k[2:]) for k in en_keys if k[2:].isdigit()]
            max_en_idx = max(en_indices) if en_indices else 0

            en0 = texts.get("EN0", "")
            en_last = texts.get(f"EN{max_en_idx}", "")

            model_name = item.get("model", "")
            if not model_name and "metadata" in item:
                model_name = item["metadata"].get("model", "")

            data.append({
                "model":     model_name,
                "group":     item.get("group", ""),
                "source_id": item.get("source_id", ""),
                "type":      item.get("type", ""),
                "chain":     item.get("chain", []),
                "en0":       en0,
                "en_last":   en_last,
            })
    return data


# =================== Batch Processing ===================

# Cache prompt sections to avoid repeated file I/O
_PROMPT_SECTIONS: dict | None = None

def _get_prompt_sections() -> dict:
    global _PROMPT_SECTIONS
    if _PROMPT_SECTIONS is None:
        _PROMPT_SECTIONS = load_eval_prompt()
    return _PROMPT_SECTIONS


def process_batch(client: APIClient, batch: list, max_retries: int = 3) -> list:
    sections = _get_prompt_sections()
    system_prompt = sections.get("SYSTEM_PROMPT", "You are a strict translation evaluator. Return only valid JSON.")
    user_preamble = sections.get("USER_PREAMBLE", "")

    # Build user message: preamble + enumerated texts
    text_parts = [user_preamble]
    for item in batch:
        text_parts.append(
            f"\n[Source ID: {item['source_id']}]\n"
            f"EN0 (source): {item['en0']}\n"
            f"EN_last (final translation): {item['en_last']}"
        )

    messages = [
        ChatMessage(role="system", content=system_prompt),
        ChatMessage(role="user", content="\n".join(text_parts)),
    ]
    response_format = {"type": "json_object"}

    for attempt in range(max_retries):
        try:
            response = client.chat_completion(messages, response_format=response_format)
            if not response.content:
                raise ValueError("Empty content received from API")

            result_json = json.loads(response.content)

            evaluated_items = []
            for item in batch:
                sid = item['source_id']
                if sid not in result_json:
                    logging.warning(f"Missing source_id {sid} in LLM response.")
                    continue

                raw_dimensions = result_json[sid]
                dim_scores = compute_dim_scores(raw_dimensions)

                eval_item = {
                    "model":      item['model'],
                    "group":      item['group'],
                    "source_id":  sid,
                    "type":       item['type'],
                    "chain":      item['chain'],
                    # 5 dimension scores (0-100)
                    "irony":       dim_scores["irony"],
                    "speech_act":  dim_scores["speech_act"],
                    "register":    dim_scores["register"],
                    "uncertainty": dim_scores["uncertainty"],
                    "attitude":    dim_scores["attitude"],
                    # Raw LLM output for debugging
                    "raw_detail": raw_dimensions,
                }
                evaluated_items.append(eval_item)

            return evaluated_items

        except Exception as e:
            if attempt < max_retries - 1:
                logging.warning(f"Batch processing error ({e}). Retrying in 3s...")
                time.sleep(3)
            else:
                logging.error(f"Batch failed after {max_retries} attempts: {e}")
                return []


# =================== Main Evaluation ===================

def evaluate_all():
    print(f"Starting evaluation with model: {EVAL_MODEL}")
    print(f"Concurrency: {CONCURRENT_REQUESTS}, Batch Size: {ITEMS_PER_REQUEST}")

    client = APIClient(
        base_url=BASE_URL,
        api_key=API_KEY,
        model=EVAL_MODEL,
        api_mode="response"
    )

    results_dir = os.path.join(BASE_DIR, "3_exps", "results")
    eval_dir    = os.path.join(BASE_DIR, "3_exps", "evaluate")
    os.makedirs(eval_dir, exist_ok=True)

    jsonl_files = glob.glob(os.path.join(results_dir, "*", "*.jsonl"))
    print(f"Found {len(jsonl_files)} JSONL files to evaluate.")

    all_data = []
    for f in jsonl_files:
        all_data.extend(extract_data_from_jsonl(f))
    print(f"Extracted {len(all_data)} items to evaluate.")

    batches = [all_data[i:i + ITEMS_PER_REQUEST] for i in range(0, len(all_data), ITEMS_PER_REQUEST)]

    results = []
    output_file = os.path.join(eval_dir, f"evaluation_results_{int(time.time())}.jsonl")
    print(f"Results will be saved to: {output_file}")

    with ThreadPoolExecutor(max_workers=CONCURRENT_REQUESTS) as executor:
        futures = {executor.submit(process_batch, client, batch): batch for batch in batches}
        for future in tqdm(as_completed(futures), total=len(batches), desc="Processing Batches"):
            batch_result = future.result()
            if batch_result:
                results.extend(batch_result)
                with open(output_file, 'a', encoding='utf-8') as out_f:
                    for res in batch_result:
                        out_f.write(json.dumps(res, ensure_ascii=False) + '\n')

    print(f"\nEvaluation complete! {len(results)}/{len(all_data)} items evaluated.")
    print(f"Results saved to {output_file}")


if __name__ == "__main__":
    try:
        evaluate_all()
    except KeyboardInterrupt:
        print("\nInterrupted by user. Exiting...")
