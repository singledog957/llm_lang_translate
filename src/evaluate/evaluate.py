import os
import sys
import json
import time
import logging
import pandas as pd
from tqdm import tqdm

# 将项目根目录添加到 sys.path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
from src.api_client import APIClient, ChatMessage

logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')

# 加载配置
load_dotenv()

BASE_URL = os.environ.get("BASE_URL", "https://www.packyapi.com/v1")
API_KEY  = os.environ.get("API_KEY", "sk-6s7eF1YA8B35EiJkaX188UIr3LiJtk8LXK32MVIDy3AXfB1E")
MODEL    = "gpt-5.5"

def evaluate():
    print(f"Starting evaluation with model: {MODEL}")
    
    client = APIClient(
        base_url=BASE_URL,
        api_key=API_KEY,
        model=MODEL,
        api_mode="response"
    )

    file_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "1_data", "results(1).xlsx")
    print(f"Loading data from: {file_path}")
    df = pd.read_excel(file_path)

    target_ids = ['EN-5', 'EN-6', 'EN-7', 'EN-8']
    
    metrics = [
        "讽刺、暗示、间接意义是否保留",
        "请求、建议、拒绝等功能是否保持",
        "礼貌程度、语域、身份关系是否漂移",
        "不确定性表达是否保留",
        "态度强度是否改变"
    ]
    
    # 确保列存在
    for metric in metrics:
        if metric not in df.columns:
            df[metric] = pd.NA
            
    # 计算需要处理的行数
    target_indices = df[df['source_id'].isin(target_ids)].index
    print(f"Found {len(target_indices)} rows to evaluate.")
    
    for index in tqdm(target_indices, desc="Evaluating translations"):
        row = df.loc[index]
        en0_text = str(row['EN0'])
        en3_text = str(row['EN3'])
        
        prompt = f"""
请评估以下从EN0到EN3的翻译表现。
源文本(EN0): {en0_text}
翻译文本(EN3): {en3_text}

请对以下5个维度进行打分，每项满分100分。请以JSON格式返回结果，使用以下具体的键名：
1. "讽刺、暗示、间接意义是否保留"
2. "请求、建议、拒绝等功能是否保持"
3. "礼貌程度、语域、身份关系是否漂移" (注意：得分越高代表没有漂移/保持得越好)
4. "不确定性表达是否保留"
5. "态度强度是否改变" (注意：得分越高代表没有改变/保持得越好)

仅返回纯JSON，不要有多余的格式或说明。示例：
{{
    "讽刺、暗示、间接意义是否保留": 90,
    "请求、建议、拒绝等功能是否保持": 85,
    "礼貌程度、语域、身份关系是否漂移": 95,
    "不确定性表达是否保留": 80,
    "态度强度是否改变": 100
}}
"""
        messages = [
            ChatMessage(role="system", content="你是一个专业的语言翻译评估专家，严格遵守用户的格式要求，始终输出合法的JSON格式。"),
            ChatMessage(role="user", content=prompt)
        ]
        
        response_format = {"type": "json_object"}
        
        max_retries = 3
        for attempt in range(max_retries):
            try:
                response = client.chat_completion(
                    messages,
                    response_format=response_format
                )
                
                if not response.content:
                    raise ValueError("Empty content received from API.")
                
                result_json = json.loads(response.content)
                for metric in metrics:
                    if metric in result_json:
                        df.at[index, metric] = result_json[metric]
                        
                # 成功后跳出重试循环
                break
                        
            except Exception as e:
                if attempt < max_retries - 1:
                    logging.warning(f"Error evaluating row {index} (source_id: {row['source_id']}): {e}. Retrying in 3 seconds...")
                    time.sleep(3)
                else:
                    logging.error(f"Failed to evaluate row {index} after {max_retries} attempts. Error: {e}")
                    
        # 增量保存，避免中断导致数据丢失
        if (index + 1) % 5 == 0:
            df.to_excel(file_path, index=False)
                
    # 保存最后结果
    print("Saving updated results...")
    df.to_excel(file_path, index=False)
    print("Evaluation completed and saved to", file_path)

if __name__ == "__main__":
    try:
        evaluate()
    except KeyboardInterrupt:
        print("\nInterrupted by user. Exiting...")
