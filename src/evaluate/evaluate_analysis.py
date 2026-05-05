import os
import json
import glob
import pandas as pd
import matplotlib.pyplot as plt
import seaborn as sns
import warnings

# 忽略字体警告
warnings.filterwarnings('ignore')

# 尝试设置中文字体，如果系统中没有相关字体，则可能会显示方块
plt.rcParams['font.sans-serif'] = ['SimHei', 'WenQuanYi Micro Hei', 'Microsoft YaHei']
plt.rcParams['axes.unicode_minus'] = False

def load_evaluation_data(eval_dir):
    """加载 evaluate 目录下的所有 jsonl 结果文件"""
    data = []
    files = glob.glob(os.path.join(eval_dir, "*.jsonl"))
    for f in files:
        with open(f, 'r', encoding='utf-8') as file:
            for line in file:
                if line.strip():
                    data.append(json.loads(line))
    return pd.DataFrame(data)

_cache_texts = {}
def fetch_text_from_results(base_dir, model, group, source_id):
    """从原始结果文件中提取文本，并使用缓存优化读取速度"""
    cache_key = f"{model}_{group}_{source_id}"
    if cache_key in _cache_texts:
        return _cache_texts[cache_key]
        
    results_dir = os.path.join(base_dir, "3_exps", "results")
    matched_files = glob.glob(os.path.join(results_dir, "*", f"{group}.jsonl"))
    
    for f in matched_files:
        with open(f, 'r', encoding='utf-8') as file:
            for line in file:
                if not line.strip(): continue
                item = json.loads(line)
                sid = item.get("source_id")
                m = item.get("model", "")
                if not m and "metadata" in item:
                    m = item["metadata"].get("model", "")
                
                texts = item.get("texts", {})
                en_keys = [k for k in texts.keys() if k.startswith("EN")]
                en_indices = [int(k[2:]) for k in en_keys if k[2:].isdigit()]
                max_en_idx = max(en_indices) if en_indices else 0
                en0 = texts.get("EN0", "")
                en_last = texts.get(f"EN{max_en_idx}", "")
                
                _cache_texts[f"{m}_{group}_{sid}"] = (en0, en_last)
                
    return _cache_texts.get(cache_key, ("(Text not found)", "(Text not found)"))

def main():
    print("Starting evaluation analysis...")
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    eval_dir = os.path.join(base_dir, "3_exps", "evaluate")
    out_dir = os.path.join(eval_dir, "analysis_results")
    os.makedirs(out_dir, exist_ok=True)
    
    df = load_evaluation_data(eval_dir)
    if df.empty:
        print("No evaluation data found in", eval_dir)
        return
        
    # 定义五个维度的列名 (Metrics defined in English)
    metrics = [
        "Irony & Implication Preservation",
        "Speech Act Maintenance",
        "Politeness & Register Shifts",
        "Uncertainty Preservation",
        "Attitudinal Intensity Changes"
    ]
    
    # 将原始数据中的中文键名映射为英文 (Map Chinese keys to English)
    column_mapping = {
        "讽刺、暗示、间接意义是否保留": "Irony & Implication Preservation",
        "请求、建议、拒绝等功能是否保持": "Speech Act Maintenance",
        "礼貌程度、语域、身份关系是否漂移": "Politeness & Register Shifts",
        "不确定性表达是否保留": "Uncertainty Preservation",
        "态度强度是否改变": "Attitudinal Intensity Changes"
    }
    df = df.rename(columns=column_mapping)
    
    # 清洗数据，确保分数为数值格式
    for m in metrics:
        df[m] = pd.to_numeric(df[m], errors='coerce')
        
    # 计算每一条文本在5个维度上的平均分
    df['average_score'] = df[metrics].mean(axis=1)
    
    # ==========================
    # 1. 按照 Model 和 Group 聚合
    # ==========================
    print("Generating Model & Group analysis...")
    avg_by_model_group = df.groupby(['model', 'group'])['average_score'].mean().reset_index()
    avg_by_model_group.to_csv(os.path.join(out_dir, "average_scores_by_model_group.csv"), index=False)
    
    plt.figure(figsize=(12, 6))
    sns.barplot(data=avg_by_model_group, x='model', y='average_score', hue='group')
    plt.title('Average Translation Score by Model and Group')
    plt.xticks(rotation=45, ha='right')
    plt.ylabel('Average Score')
    plt.legend(title='Group', bbox_to_anchor=(1.05, 1), loc='upper left')
    plt.tight_layout()
    plt.savefig(os.path.join(out_dir, "average_scores_bar.png"))
    plt.close()

    # ==========================
    # 2. 按照维度 (Metrics) 聚合的热力图
    # ==========================
    print("Generating Metrics Heatmap...")
    avg_by_model_metric = df.groupby('model')[metrics].mean().reset_index()
    avg_by_model_metric.to_csv(os.path.join(out_dir, "average_scores_by_model_metric.csv"), index=False)
    
    plt.figure(figsize=(10, 8))
    sns.heatmap(avg_by_model_metric.set_index('model').T, annot=True, cmap="YlGnBu", fmt=".1f")
    plt.title('Average Metrics Score by Model')
    plt.tight_layout()
    plt.savefig(os.path.join(out_dir, "metrics_heatmap.png"))
    plt.close()

    # ==========================
    # 3. 提取 Model 的最高分和最低分
    # ==========================
    print("Extracting highest and lowest performing texts for each model...")
    report_lines = ["# 翻译评估分析报告 (Evaluation Analysis Report)\n"]
    
    models = df['model'].dropna().unique()
    for m in models:
        model_df = df[df['model'] == m].dropna(subset=['average_score'])
        if model_df.empty: continue
        
        # 找出最高分和最低分的行
        highest_idx = model_df['average_score'].idxmax()
        lowest_idx = model_df['average_score'].idxmin()
        highest_row = model_df.loc[highest_idx]
        lowest_row = model_df.loc[lowest_idx]
        
        # 提取原文和翻译文本
        en0_high, en_last_high = fetch_text_from_results(base_dir, m, highest_row['group'], highest_row['source_id'])
        en0_low, en_last_low = fetch_text_from_results(base_dir, m, lowest_row['group'], lowest_row['source_id'])
        
        report_lines.append(f"## 模型 (Model): {m}")
        report_lines.append(f"- **模型整体平均分 (Overall Average Score)**: {model_df['average_score'].mean():.2f}\n")
        
        report_lines.append(f"### 表现最好的文本 (Best Performing Text) - 得分: {highest_row['average_score']:.2f}")
        report_lines.append(f"- **Group**: {highest_row['group']}")
        report_lines.append(f"- **Source ID**: {highest_row['source_id']}")
        report_lines.append(f"- **英文原文 (EN0)**: {en0_high}")
        report_lines.append(f"- **最终翻译回英文 (EN_last)**: {en_last_high}\n")
        
        report_lines.append(f"### 表现最差的文本 (Worst Performing Text) - 得分: {lowest_row['average_score']:.2f}")
        report_lines.append(f"- **Group**: {lowest_row['group']}")
        report_lines.append(f"- **Source ID**: {lowest_row['source_id']}")
        report_lines.append(f"- **英文原文 (EN0)**: {en0_low}")
        report_lines.append(f"- **最终翻译回英文 (EN_last)**: {en_last_low}\n")
        report_lines.append("---\n")
        
    with open(os.path.join(out_dir, "analysis_report.md"), 'w', encoding='utf-8') as f:
        f.write("\n".join(report_lines))
        
    print(f"Analysis complete! Results saved to: {out_dir}")
    print(f"- average_scores_bar.png (柱状图)")
    print(f"- metrics_heatmap.png (维度热力图)")
    print(f"- analysis_report.md (极值文本分析报告)")

if __name__ == "__main__":
    main()
