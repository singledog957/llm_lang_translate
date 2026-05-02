# 模块架构与代理设计

## 模块依赖图

```
.env ──→ APIClient
config.yaml ──→ ExperimentRunner
prompts/ ──→ PromptManager

APIClient ──→ Translator
PromptManager ──→ Translator
Translator ──→ ExperimentRunner
DataIO ──→ ExperimentRunner
ExperimentLogger ──→ ExperimentRunner

ExperimentRunner ──→ run_experiment.py (主入口)
```

## 各模块详解

### 1. APIClient (`src/api_client.py`)

**职责**：封装 OpenAI SDK 的同步 HTTP 调用。

- 无状态：每次 `chat_completion()` 是独立请求
- 内置重试：指数退避处理 `RateLimitError` 和 `APIError`
- 请求间隔：`request_interval` 防止触发速率限制
- 参数注入：`base_url`, `api_key`, `model` 均从外部传入

**关键接口**：
```python
client.chat_completion(messages: list[ChatMessage]) -> APIResponse
```

---

### 2. DataIO (`src/data_io.py`)

**职责**：数据读取与结果序列化。

- 解析 `source_XX.md`：按正则 `^[A-Z]+-\d+$` 匹配 ID 行
- 支持语言前缀过滤和数量限制
- 输出 JSON（单条）、JSONL（批量）、Markdown（人类可读）

---

### 3. PromptManager (`src/prompt_manager.py`)

**职责**：管理 prompt 模板的加载和渲染。

- 模板文件命名：`{name}_{lang}.txt`（如 `translate_EN.txt`）
- 变量替换：`{source_lang}`, `{target_lang}`, `{text}`
- 批量模式：通过 `batch_wrapper` 模板将多个任务组装为一个 prompt
- 自动选择模板：根据 `is_paraphrase` / `is_backtranslation` 标志

**批量 prompt 结构**：
```
[batch_wrapper 模板]
  === Task 1 ===
  [translate/paraphrase/backtranslate 模板渲染结果]
  === Task 2 ===
  ...
  期望输出格式:
  === Result 1 ===
  ...
```

---

### 4. Translator (`src/translator.py`)

**职责**：执行翻译调用，解析响应。

两种模式：
- `translate_single(task)`: 单任务，一次 API 调用
- `translate_batch(tasks)`: 多任务打包为一次调用（自动退化为 single 当只有 1 个任务）

**批量响应解析**：三级回退策略
1. 按 `=== Result N ===` 标记分割
2. 按 `[N]` 标记分割
3. 按空行分割

---

### 5. ExperimentRunner (`src/experiment_runner.py`)

**职责**：实验编排与调度。

**核心逻辑**：
1. 将 N 段源文本按 `PARAGRAPHS_PER_REQUEST` 分批
2. 对每个批次，按轮次（step）执行：
### 4. Translator (翻译执行器)
- **职责**: 执行单条或批量翻译。
- **批量协议**: 
    - 使用 `render_batch` 将多个任务封装。
    - **JSON 协议**: 强制要求模型返回 `{"results": ["...", "..."]}` 格式。
    - **结构化输出**: 调用 API 时启用 `response_format={"type": "json_object"}`。
- **解析鲁棒性**: 
    - 优先 JSON 解析 $\rightarrow$ 代码块提取 $\rightarrow$ 正则匹配回退。
    - 若完全失败，保存原始响应至 `failed_response_debug.json` 并中断实验。

### 5. ExperimentLogger (过程记录器)
- **日志**: 生成 `api_calls.jsonl`（完整记录）和 `progress.json`（进度状态）。
- **断点续做**: 
    - 自动检查 `progress.json`。
    - **自动恢复**: 若进度文件缺失，会通过扫描磁盘上的 `.json` 结果文件自动重建进度状态。
- **调试**: 捕获并记录 API 错误、解析异常及 Token 消耗。`summary.json`：实验摘要统计（总调用次数、tokens、耗时）

---

## 数据流

```
source_EN.md
    │
    ▼
[DataIO.load_source_texts] ─→ list[SourceText]
    │
    ▼
[ExperimentRunner.run_all]
    │
    ├─ 按 PARAGRAPHS_PER_REQUEST 分批
    │
    ├─ for each batch:
    │   ├─ for each step (1→2→3):
    │   │   ├─ 构建 TranslationTask × (groups × paragraphs)
    │   │   ├─ [Translator.translate_batch]
    │   │   │   ├─ [PromptManager.render_batch]
    │   │   │   ├─ [APIClient.chat_completion]
    │   │   │   └─ [_parse_batch_response]
    │   │   ├─ 更新 current_texts
    │   │   ├─ 构建回译 tasks
    │   │   └─ [Translator.translate_batch] (回译)
    │   │
    │   └─ 保存 JSON 结果
    │
    └─ 保存 JSONL + Markdown 汇总

Output: 3_exps/results/<model>_<timestamp>/
```

## 配置层次

```
.env                    # 敏感信息（API keys）+ 运行时参数
    ↓
config.yaml             # 实验定义（组、语言、路径）
    ↓
1_data/prompts/*.txt    # Prompt 模板（用户可自定义）
```

## 扩展方式

| 需求 | 方法 |
|---|---|
| 添加新实验组 | 在 `config.yaml` 的 `groups` 中追加 |
| 添加新语言 | 在 `config.yaml` 的 `languages` 中追加 |
| 自定义 Prompt | 编辑 `1_data/prompts/*.txt` |
| 切换模型 | 在 `.env` 中修改 `MODEL1_*` |
| 添加多模型对比 | 在 `.env` 中添加 `MODEL2_*`, `MODEL3_*` |
| 更多段落并行 | 调整 `.env` 中 `PARAGRAPHS_PER_REQUEST` |
