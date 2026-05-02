# 跨语言翻译链实验 — TL;DR

## 快速部署

```bash
# 1. 安装依赖
pip install -r requirements.txt

# 2. 配置 API
cp .env.example .env
# 编辑 .env：填入 MODEL1_NAME / MODEL1_BASE_URL / MODEL1_API_KEY

# 3. 验证配置（不调用 API）
python run_experiment.py --dry-run

# 4. 运行实验
python run_experiment.py

# 5. 查看结果
ls 3_exps/results/
```

## 关键配置项（.env）

| 变量 | 默认值 | 说明 |
|---|---|---|
| `MODEL1_NAME` | — | 模型名称 (e.g. `gpt-4o`) |
| `MODEL1_BASE_URL` | — | API 端点 |
| `MODEL1_API_KEY` | — | API 密钥 |
| `TEMPERATURE` | `0.0` | 生成温度 |
| `MAX_TOKENS` | `4096` | 最大输出 token |
| `PARAGRAPHS_PER_REQUEST` | `1` | 每次请求包含的段落数 |

多模型：添加 `MODEL2_*`、`MODEL3_*` 等，系统自动检测并串行执行。

## 自定义 Prompt

编辑 `1_data/prompts/` 下的模板文件。支持变量：`{source_lang}`、`{target_lang}`、`{text}`。

## 输出结构

```
3_exps/results/<model>_<timestamp>/
├── group1_EN_JA_ZH_FR/    # 每组实验
│   ├── EN-1.json           # 每段源文本的完整翻译链
│   └── ...
├── group1_EN_JA_ZH_FR.jsonl
├── group1_EN_JA_ZH_FR.md
└── logs/                   # API 调用日志
```
