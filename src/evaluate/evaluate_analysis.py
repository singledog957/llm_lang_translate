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
    base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    eval_dir = os.path.join(base_dir, "3_exps", "evaluate")
    out_dir = os.path.join(eval_dir, "analysis_results")
    os.makedirs(out_dir, exist_ok=True)
    
    df = load_evaluation_data(eval_dir)
    if df.empty:
        print("No evaluation data found in", eval_dir)
        return
        
    # 5 dimension score columns (new schema from evaluate_pure.py)
    metrics = [
        "irony",
        "speech_act",
        "register",
        "uncertainty",
        "attitude",
    ]

    # Human-readable display names for charts
    METRIC_DISPLAY = {
        "irony":       "Irony & Implication",
        "speech_act":  "Speech Act Maintenance",
        "register":    "Politeness & Register Drift",
        "uncertainty": "Uncertainty Preservation",
        "attitude":    "Attitudinal Intensity",
    }

    # Backwards compatibility: migrate old Chinese-key schema to new English keys
    legacy_mapping = {
        "\u8bbd\u523a\u3001\u6697\u793a\u3001\u95f4\u63a5\u610f\u4e49\u662f\u5426\u4fdd\u7559": "irony",
        "\u8bf7\u6c42\u3001\u5efa\u8bae\u3001\u62d2\u7edd\u7b49\u529f\u80fd\u662f\u5426\u4fdd\u6301": "speech_act",
        "\u793c\u8c8c\u7a0b\u5ea6\u3001\u8bed\u57df\u3001\u8eab\u4efd\u5173\u7cfb\u662f\u5426\u6f02\u79fb": "register",
        "\u4e0d\u786e\u5b9a\u6027\u8868\u8fbe\u662f\u5426\u4fdd\u7559": "uncertainty",
        "\u6001\u5ea6\u5f3a\u5ea6\u662f\u5426\u6539\u53d8": "attitude",
    }
    for old_col, new_col in legacy_mapping.items():
        if old_col in df.columns and new_col not in df.columns:
            df[new_col] = df[old_col]

    # Ensure score columns exist and are numeric
    for m in metrics:
        if m in df.columns:
            df[m] = pd.to_numeric(df[m], errors='coerce')
        else:
            df[m] = float('nan')

    # Drop rows where all dimension scores are missing
    df = df.dropna(subset=metrics, how='all')
    if df.empty:
        print("No scoreable data found — all dimension columns are NaN.")
        return

    # Compute per-item average across 5 dimensions
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
    plt.ylabel('Average Score (0-100)')
    plt.legend(title='Group', bbox_to_anchor=(1.05, 1), loc='upper left')
    plt.tight_layout()
    plt.savefig(os.path.join(out_dir, "average_scores_bar.png"))
    plt.close()

    # ==========================
    # 2. Per-dimension heatmap
    # ==========================
    print("Generating Metrics Heatmap...")
    avg_by_model_metric = df.groupby('model')[metrics].mean().reset_index()
    # Rename columns to display names for the chart
    display_df = avg_by_model_metric.rename(columns=METRIC_DISPLAY).set_index('model')
    avg_by_model_metric.to_csv(os.path.join(out_dir, "average_scores_by_model_metric.csv"), index=False)

    plt.figure(figsize=(10, 8))
    sns.heatmap(display_df.T, annot=True, cmap="YlGnBu", fmt=".1f", vmin=0, vmax=100)
    plt.title('Average Dimension Score by Model')
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
