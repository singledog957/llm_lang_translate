import os
import sys
import json
import time
import logging
import glob
from concurrent.futures import ThreadPoolExecutor, as_completed
from tqdm import tqdm

# 将项目根目录添加到 sys.path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
from src.api_client import APIClient, ChatMessage

logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')

# 加载配置
load_dotenv()

# ================= 配置参数 =================
ITEMS_PER_REQUEST = 4      # 每次请求发送N组文本
CONCURRENT_REQUESTS = 3    # 并发请求数M
EVAL_MODEL = "gpt-5.5"     # 评估用的模型
# ============================================

BASE_URL = os.environ.get("BASE_URL", "https://www.packyapi.com/v1")
API_KEY  = os.environ.get("API_KEY", "sk-6s7eF1YA8B35EiJkaX188UIr3LiJtk8LXK32MVIDy3AXfB1E")

def extract_data_from_jsonl(file_path):
    """提取需要评估的数据。只提取EN0和最后一次翻译的EN"""
    data = []
    with open(file_path, 'r', encoding='utf-8') as f:
        for line in f:
            if not line.strip(): continue
            item = json.loads(line)
            
            # 提取最后一种语言翻译回的英文
            texts = item.get("texts", {})
            en_keys = [k for k in texts.keys() if k.startswith("EN")]
            en_indices = [int(k[2:]) for k in en_keys if k[2:].isdigit()]
            max_en_idx = max(en_indices) if en_indices else 0
            en_last_key = f"EN{max_en_idx}"
            
            en0 = texts.get("EN0", "")
            en_last = texts.get(en_last_key, "")
            
            # 提取model字段，可能在顶层也可能在metadata中
            model_name = item.get("model", "")
            if not model_name and "metadata" in item:
                model_name = item["metadata"].get("model", "")
                
            data.append({
                "model": model_name,
                "group": item.get("group", ""),
                "source_id": item.get("source_id", ""),
                "type": item.get("type", ""),
                "chain": item.get("chain", []),
                "en0": en0,
                "en_last": en_last
            })
    return data

def process_batch(client, batch, max_retries=3):
    prompt_parts = []
    prompt_parts.append(f"请评估以下 {len(batch)} 组从源文本到最终翻译文本的翻译表现。\n")
    prompt_parts.append("""
请对以下5个维度进行打分，每项满分100分。**请采用极其严格的标准**，任何细微的语义流失、语气变化、细节省略或语域不匹配都应大幅扣分。得高分说明保留得非常好，漂移得分低说明漂移严重（即保留得差）。

请以纯JSON格式返回结果，**必须严格以对应的 source_id 为键**，值为包含5个维度打分的字典。具体维度键名如下：
1. "讽刺、暗示、间接意义是否保留"
2. "请求、建议、拒绝等功能是否保持"
3. "礼貌程度、语域、身份关系是否漂移"
4. "不确定性表达是否保留"
5. "态度强度是否改变"

示例格式：
{
  "EN-1": {
    "讽刺、暗示、间接意义是否保留": 70,
    "请求、建议、拒绝等功能是否保持": 85,
    "礼貌程度、语域、身份关系是否漂移": 60,
    "不确定性表达是否保留": 80,
    "态度强度是否改变": 75
  }
}

待评估文本如下：
""")

    for item in batch:
        prompt_parts.append(f"\n[Source ID: {item['source_id']}]\n源文本: {item['en0']}\n最终翻译文本: {item['en_last']}")
        
    prompt = "".join(prompt_parts)
    messages = [
        ChatMessage(role="system", content="你是一个极度严苛的专业语言翻译评估专家。你必须严格遵守用户的JSON格式要求，不要输出任何多余的解释。"),
        ChatMessage(role="user", content=prompt)
    ]
    response_format = {"type": "json_object"}
    
    for attempt in range(max_retries):
        try:
            response = client.chat_completion(
                messages,
                response_format=response_format
            )
            if not response.content:
                raise ValueError("Empty content received from API")
                
            result_json = json.loads(response.content)
            
            evaluated_items = []
            for item in batch:
                sid = item['source_id']
                if sid in result_json:
                    scores = result_json[sid]
                    eval_item = {
                        "model": item['model'],
                        "group": item['group'],
                        "source_id": sid,
                        "type": item['type'],
                        "chain": item['chain'],
                        "讽刺、暗示、间接意义是否保留": scores.get("讽刺、暗示、间接意义是否保留"),
                        "请求、建议、拒绝等功能是否保持": scores.get("请求、建议、拒绝等功能是否保持"),
                        "礼貌程度、语域、身份关系是否漂移": scores.get("礼貌程度、语域、身份关系是否漂移"),
                        "不确定性表达是否保留": scores.get("不确定性表达是否保留"),
                        "态度强度是否改变": scores.get("态度强度是否改变")
                    }
                    evaluated_items.append(eval_item)
                else:
                    logging.warning(f"Missing source_id {sid} in LLM response.")
            return evaluated_items
            
        except Exception as e:
            if attempt < max_retries - 1:
                logging.warning(f"Batch processing error ({e}). Retrying in 3s...")
                time.sleep(3)
            else:
                logging.error(f"Batch processing failed after {max_retries} attempts. Error: {e}")
                return []

def evaluate_all():
    print(f"Starting pure evaluation with model: {EVAL_MODEL}")
    print(f"Concurrency: {CONCURRENT_REQUESTS}, Batch Size: {ITEMS_PER_REQUEST}")
    
    client = APIClient(
        base_url=BASE_URL,
        api_key=API_KEY,
        model=EVAL_MODEL,
        api_mode="response"
    )

    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    results_dir = os.path.join(base_dir, "3_exps", "results")
    eval_dir = os.path.join(base_dir, "3_exps", "evaluate")
    
    os.makedirs(eval_dir, exist_ok=True)
    
    jsonl_files = glob.glob(os.path.join(results_dir, "*", "*.jsonl"))
    print(f"Found {len(jsonl_files)} JSONL files to evaluate.")
    
    all_data = []
    for f in jsonl_files:
        all_data.extend(extract_data_from_jsonl(f))
        
    print(f"Extracted {len(all_data)} items to evaluate.")
    
    # 拆分批次
    batches = [all_data[i:i + ITEMS_PER_REQUEST] for i in range(0, len(all_data), ITEMS_PER_REQUEST)]
    
    results = []
    output_file = os.path.join(eval_dir, f"evaluation_results_{int(time.time())}.jsonl")
    print(f"Results will be saved to: {output_file}")
    
    # 使用线程池并发请求
    with ThreadPoolExecutor(max_workers=CONCURRENT_REQUESTS) as executor:
        # 提交所有任务
        futures = {executor.submit(process_batch, client, batch): batch for batch in batches}
        
        # 处理完成的任务
        for future in tqdm(as_completed(futures), total=len(batches), desc="Processing Batches"):
            batch_result = future.result()
            if batch_result:
                results.extend(batch_result)
                # 增量写入结果文件
                with open(output_file, 'a', encoding='utf-8') as out_f:
                    for res in batch_result:
                        out_f.write(json.dumps(res, ensure_ascii=False) + '\n')
                        
    print(f"\nEvaluation completed! Successfully evaluated {len(results)}/{len(all_data)} items.")
    print(f"Final results saved to {output_file}")

if __name__ == "__main__":
    try:
        evaluate_all()
    except KeyboardInterrupt:
        print("\nInterrupted by user. Exiting...")
