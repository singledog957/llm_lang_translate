# 多语言文本采集系统

用于研究**相同内容在不同语言下对大模型思考差异**的数据采集管线。支持 RSS、官方 API、Wikipedia 等多种来源，输出统一格式的 JSONL/Parquet 数据集。

---

## 快速开始

```bash
# 1. 安装依赖
pip install feedparser trafilatura httpx langdetect pydantic pydantic-settings \
            loguru rich pyarrow sqlalchemy pyyaml

# 2. 验证配置
python cli.py validate

# 3. 查看数据源列表
python cli.py sources

# 4. 执行采集
python cli.py collect
```

---

## 目录结构

```
collector/
├── cli.py                   # 命令行入口
├── config/
│   ├── config.yaml          # 主配置（时间、语言、领域、数量、输出）
│   └── sources.yaml         # 数据源配置（用户主要编辑此文件）
├── src/
│   ├── models.py            # 数据模型 + 配置加载
│   ├── engine.py            # 采集引擎（协调、配额管理）
│   ├── collectors/
│   │   ├── __init__.py      # 采集器工厂
│   │   ├── base.py          # BaseCollector + RssCollector + WikiCollector
│   │   └── api_collectors.py # GuardianCollector + ArxivCollector
│   ├── processors/
│   │   └── pipeline.py      # 语言检测、长度过滤、去重
│   └── storage/
│       └── writer.py        # JSONL / Parquet 写出
├── datasets/                # 输出目录（按语言分子目录）
└── logs/                    # 运行日志
```

---

## 配置说明

### `config/config.yaml` — 主配置

```yaml
collection:
  time_range:
    start: "2024-01-01"   # 留空 "" 表示不限
    end: "2024-12-31"

  languages: [zh, en, ja, fr, de]   # ISO 639-1 语言码
  domains: [technology, politics, finance, science, culture, health]

  limits:
    total: 1000          # 总条数上限（0 = 不限）
    per_source: 200      # 每个来源上限
    per_language: 300    # 每种语言上限
    per_domain: 200      # 每个领域上限

  schedule:
    mode: "once"         # once | interval
    interval_hours: 12

processing:
  min_word_count: 80     # 过短丢弃
  max_word_count: 50000
  dedup_enabled: true

output:
  format: "jsonl"        # jsonl | parquet
  path: "./datasets"
  split_by_language: true
```

### `config/sources.yaml` — 数据源配置（重点）

每个来源支持以下字段：

| 字段 | 说明 |
|------|------|
| `name` | 来源名称（必填） |
| `type` | `rss` / `api_guardian` / `api_arxiv` / `wiki` / `custom_rss` |
| `enabled` | `true`/`false` 快速开关 |
| `language` | ISO 639-1 语言码 |
| `domains` | 该来源涵盖的领域列表 |
| `feeds` | RSS 类型的 feed 列表（含 `url` 和 `domain_hint`）|
| `api_key` | API 鉴权 key，支持 `${ENV_VAR}` 形式 |
| `extra` | 来源专属附加参数 |

**添加自定义 RSS 来源示例：**

```yaml
- name: "我的技术博客"
  type: "rss"
  enabled: true
  language: "zh"
  domains: [technology]
  feeds:
    - url: "https://example.com/feed.xml"
      domain_hint: technology
```

**添加多 feed 来源：**

```yaml
- name: "多栏目新闻站"
  type: "rss"
  enabled: true
  language: "en"
  domains: [politics, science]
  feeds:
    - url: "https://news.example.com/politics/rss"
      domain_hint: politics
    - url: "https://news.example.com/science/rss"
      domain_hint: science
```

---

## 命令行用法

```bash
# 单次采集（使用配置文件默认值）
python cli.py collect

# 覆盖语言和领域
python cli.py collect --languages zh en --domains technology politics

# 限制数量
python cli.py collect --total 500 --per-source 50

# 指定时间范围
python cli.py collect --start 2024-06-01 --end 2024-12-31

# 只使用特定来源
python cli.py collect --source-names "BBC News (EN)" "Le Monde RSS"

# 指定输出格式和路径
python cli.py collect --format parquet --output ./my_dataset

# 定时采集（按 config.yaml 中的 interval_hours）
python cli.py schedule

# 列出所有数据源状态
python cli.py sources

# 验证配置文件语法
python cli.py validate
```

---

## 输出格式

### JSONL（默认，按语言分文件）

```
datasets/
├── en/en.jsonl
├── zh/zh.jsonl
├── ja/ja.jsonl
├── fr/fr.jsonl
└── de/de.jsonl
```

### 每条记录的 Schema

```json
{
  "id": "550e8400-e29b-41d4-a716-446655440000",
  "source": {
    "name": "BBC News (EN)",
    "url": "https://www.bbc.com/news/technology-12345",
    "type": "rss",
    "country": ""
  },
  "language": "en",
  "domain": "technology",
  "title": "Article Title",
  "content": "Full article body text...",
  "summary": "Brief summary if available",
  "author": "Author Name",
  "published_at": "2024-03-15T08:30:00Z",
  "collected_at": "2024-03-15T09:00:00Z",
  "word_count": 850,
  "char_count": 4200,
  "metadata": {
    "feed_url": "https://feeds.bbci.co.uk/news/technology/rss.xml",
    "detected_language": "en"
  }
}
```

### 读取数据集

```python
import json

# 读取某一语言的数据
with open("datasets/en/en.jsonl", encoding="utf-8") as f:
    articles = [json.loads(line) for line in f]

# 按领域过滤
tech = [a for a in articles if a["domain"] == "technology"]

# Parquet 读取（需要 pyarrow 或 pandas）
import pandas as pd
df = pd.read_parquet("datasets/en/en.parquet")
```

---

## 内置数据源

| 来源 | 类型 | 语言 | 领域 | API Key 需要 |
|------|------|------|------|:---:|
| The Guardian | API | EN | 全领域 | ✓（免费注册） |
| Reuters | RSS | EN | 政治、财经、科技 | ✗ |
| BBC News | RSS | EN | 全领域 | ✗ |
| arXiv | API | EN | 科学、技术 | ✗ |
| BBC 中文 | RSS | ZH | 政治、文化 | ✗ |
| 德国之声中文 | RSS | ZH | 政治 | ✗ |
| NHK World | RSS | JA | 政治、科学 | ✗ |
| Deutsche Welle | RSS | JA/FR/DE | 政治 | ✗ |
| Le Monde | RSS | FR | 政治、科学、文化 | ✗ |
| Spiegel Online | RSS | DE | 政治、文化 | ✗ |
| Wikipedia | API | EN/ZH/... | 可配置 | ✗ |

**The Guardian API Key 免费注册：** https://open-platform.theguardian.com/

配置方式（两种均可）：
```bash
# 方式一：环境变量
export GUARDIAN_API_KEY=your_key_here

# 方式二：直接写入 sources.yaml
api_key: "your_key_here"
```

---

## 扩展新采集器

在 `src/collectors/` 下新建文件，继承 `BaseCollector`：

```python
from src.collectors.base import BaseCollector
from src.models import Article, ArticleSource

class MyCollector(BaseCollector):
    async def collect(self):
        # 实现采集逻辑，使用 yield 产出 Article 对象
        article = Article(
            source=ArticleSource(name=self.source.name, url="...", type="custom"),
            language=self.source.language,
            domain=self.source.domains[0],
            title="标题",
            content="正文内容...",
        )
        yield article
```

然后在 `src/collectors/__init__.py` 的 `mapping` 字典中注册：

```python
mapping = {
    ...
    "my_type": MyCollector,
}
```

最后在 `sources.yaml` 中使用：

```yaml
- name: "我的自定义采集器"
  type: "my_type"
  enabled: true
  language: "en"
  domains: [technology]
```

---

## 支持的领域标签

| 标签 | 含义 |
|------|------|
| `technology` | 科技 |
| `politics` | 政治 |
| `finance` | 财经 |
| `science` | 科学 |
| `culture` | 文化艺术 |
| `health` | 医疗健康 |
| `sports` | 体育 |
| `environment` | 环境 |
| `education` | 教育 |
| `entertainment` | 娱乐 |

### 领域自动分类 (DomainPicker)
系统内置了一个跨语言的自动领域分类器（`src/processors/domain_picker.py`）。
即使配置的采集源只指定了粗略的 `domain_hint`，系统在采集到文章后，仍会通过扫描标题和正文中的多语言特征词（支持英文、中文、日文、德文、法文），基于加权打分（标题命中得2分，正文命中得1分）自动将文章分配到更精准的领域中。这极大减少了因为粗放的 RSS 源导致领域分类不准确的问题。

---

## 依赖清单

```
feedparser        # RSS/Atom 解析
trafilatura       # 网页正文提取
httpx             # 异步 HTTP 客户端
langdetect        # 语言检测
pydantic          # 数据模型与验证
pydantic-settings # 配置加载
loguru            # 日志
rich              # 终端输出美化
pyarrow           # Parquet 支持
pyyaml            # YAML 解析
tencentcloud-sdk-python # 腾讯云 API SDK（用于翻译功能）
```

## 数据翻译

本项目提供了基于腾讯云的翻译脚本，支持将已抓取的数据批量翻译为其他语言。

### 配置翻译

编辑 `config/translate.yaml` 文件：

```yaml
translation:
  source_languages: 
    - en
    - zh
  target_languages:
    - es
    - ja
  max_items_per_lang: 10
```

### 运行翻译

确保您的 `.env` 文件中配置了腾讯云的 `SecretId` 和 `SecretKey`，然后运行：

```bash
python translate.py
```
