import os
import json
from collections import Counter
from glob import glob

def print_stats(dataset_dir="./datasets"):
    print(f"正在分析目录: {dataset_dir} ...")
    
    if not os.path.exists(dataset_dir):
        print("未找到 datasets 目录，说明尚未成功写入任何数据。")
        return
        
    jsonl_files = glob(os.path.join(dataset_dir, "**/*.jsonl"), recursive=True)
    if not jsonl_files:
        print("在目录中未找到任何 .jsonl 数据文件。")
        return
        
    total_articles = 0
    lang_counter = Counter()
    domain_counter = Counter()
    source_counter = Counter()
    
    for file_path in jsonl_files:
        with open(file_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    data = json.loads(line)
                    total_articles += 1
                    
                    lang = data.get("language", "unknown")
                    domain = data.get("domain", "unknown")
                    
                    # 从 source 对象中提取名称
                    source = data.get("source", {})
                    if isinstance(source, dict):
                        source_name = source.get("name", "unknown")
                    else:
                        source_name = str(source)
                    
                    lang_counter[lang] += 1
                    domain_counter[domain] += 1
                    source_counter[source_name] += 1
                    
                except json.JSONDecodeError:
                    pass

    print("\n" + "="*40)
    print("📊 数据采集统计报告")
    print("="*40)
    
    print(f"\n【总计】采集文章数: {total_articles} 条")
    
    print("\n--- 按语言分布 ---")
    for lang, count in lang_counter.most_common():
        print(f"  {lang.upper().ljust(4)} : {count} 条")
        
    print("\n--- 按领域分布 ---")
    for domain, count in domain_counter.most_common():
        print(f"  {domain.ljust(12)} : {count} 条")
        
    print("\n--- 按数据源分布 ---")
    for source, count in source_counter.most_common():
        print(f"  {source.ljust(25)} : {count} 条")
        
    print("\n" + "="*40)

if __name__ == "__main__":
    print_stats()
