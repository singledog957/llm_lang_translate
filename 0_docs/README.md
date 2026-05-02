# 跨语言翻译链实验系统 — 工程架构

## 项目概述

本系统用于论文《大语言模型的跨语言中介表征与语义—语用坍缩》实验二的数据采集。通过调用 OpenAI-compatible Chat Completion API，执行多轮跨语言翻译链实验，观察语义—语用信息在传递过程中的选择性损失。

## 实验设计

| 组别 | 链条 | 类型 |
|---|---|---|
| 实验组1 | EN→JA→ZH→FR | 跨文字系统链 |
| 实验组2 | EN→FR→ZH→JA | 跨文字系统链 |
| 对照组3 | EN→FR→DE→IT | 欧洲语言链 |
| 对照组4 | EN→EN→EN→EN | 单语改写链 |

每步翻译后，还会执行**回译**（翻译回原文语言 EN），以便对比各轮次的语义损失。
例如实验组1最终输出：`EN0, JA, EN1, ZH, EN2, FR, EN3`

## 目录结构

```
6_LLM_Lang/
├── .env.example              # API 配置模板
├── config.yaml               # 实验配置（组、语言、参数）
├── requirements.txt          # Python 依赖
├── run_experiment.py          # 主入口
├── tldr.md                   # 快速部署指南
│
├── src/                      # 核心模块
│   ├── api_client.py         # OpenAI API 封装
│   ├── data_io.py            # 数据读写
│   ├── prompt_manager.py     # Prompt 模板管理
│   ├── translator.py         # 翻译执行器
│   ├── experiment_runner.py  # 实验调度器
│   └── logger.py             # 过程记录
│
├── 0_docs/                   # 文档
│   ├── README.md             # 本文件
│   ├── agents.md             # 架构与模块说明
│   └── essay.md              # 论文构想
│
├── 1_data/                   # 数据与 Prompt
│   ├── source/
│   │   ├── source_EN.md      # 英文源文本 (EN-1~EN-20)
│   │   └── source_ZH.md      # 中文源文本 (ZH-1~ZH-20)
│   └── prompts/
│       ├── translate_EN.txt  # 翻译 prompt
│       ├── paraphrase_EN.txt # 改写 prompt
│       ├── backtranslate_EN.txt
│       └── batch_wrapper_EN.txt
│
└── 3_exps/results/           # 实验输出（按模型+时间戳）
    └── <model>_<timestamp>/
        ├── group1_.../
        ├── group2_.../
        ├── *.jsonl / *.md
        └── logs/
```

## 技术栈

- **语言**: Python 3.10+
- **API**: OpenAI Chat Completion (兼容所有 OpenAI-compatible 端点)
- **依赖**: `openai`, `python-dotenv`, `pyyaml`

## 输出格式

每段源文本生成一个 JSON 文件，包含完整翻译链的所有中间文本和元数据。
各组实验还生成 JSONL（机器可读）和 Markdown（人类可读）汇总文件。

## 多模型支持

在 `.env` 中配置多组 `MODEL{N}_*` 变量，系统自动检测并按顺序串行执行全部实验。
每个模型的结果保存在独立的时间戳目录中，避免覆盖。
