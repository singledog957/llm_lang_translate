# TL;DR: Data Crawler & Translator

## 核心功能
1. **多语言新闻/文章抓取**: 支持10种语言(英/中/日/韩/法/德/西/俄/葡/意)的RSS订阅源抓取和正文提取。
2. **自动化翻译**: 基于腾讯云翻译 API，支持已抓取数据的全自动多语言互译。
3. **领域分类**: 使用关键字匹配对文章进行领域划分(政治、科技、科学等)。

## 快速开始

### 1. 抓取数据
```bash
# 执行抓取脚本，配置可在 config/feeds.yaml 中调整
python cli.py fetch --max-items 50
```

### 2. 翻译数据
编辑 `config/translate.yaml` 配置文件，设置目标语言。
配置 `.env` 文件填入腾讯云 API 密钥。
```bash
python translate.py
```

### 3. 查看统计
```bash
python stats.py
```

更详细的架构和说明请查看 [README.md](README.md)。
