import os
import json
import yaml
import shutil
from pathlib import Path
from src.processors.translator import Translator
from loguru import logger

def load_config(config_path="config/translate.yaml"):
    if not os.path.exists(config_path):
        logger.error(f"Config file {config_path} not found.")
        return None
    with open(config_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)

def translate_long_text(translator, text, source_lang, target_lang, chunk_size=4000):
    """
    对长文本进行分块翻译并拼接
    chunk_size: 默认4000，略低于腾讯云单次请求限制，留出余量
    """
    if not text:
        return ""
    
    translated_chunks = []
    for i in range(0, len(text), chunk_size):
        chunk = text[i:i+chunk_size]
        res = translator.translate_text(chunk, source_lang, target_lang)
        if res:
            translated_chunks.append(res)
        else:
            logger.warning(f"Failed to translate chunk {i//chunk_size + 1}")
            # 如果某一块失败，返回已有或者空，或者抛错。这里选择部分拼接
    return "".join(translated_chunks)

def main():
    config = load_config()
    if not config or "translation" not in config:
        return
    
    trans_config = config["translation"]
    source_languages = trans_config.get("source_languages", [])
    target_languages = trans_config.get("target_languages", [])
    max_items = trans_config.get("max_items_per_lang", 0)
    
    if not target_languages:
        logger.error("No target languages specified in config.")
        return
        
    translator = Translator()
    
    datasets_dir = "./datasets"
    if not os.path.exists(datasets_dir):
        logger.error(f"Datasets directory {datasets_dir} not found.")
        return
        
    for lang_dir in os.listdir(datasets_dir):
        lang_path = os.path.join(datasets_dir, lang_dir)
        if not os.path.isdir(lang_path):
            continue
            
        if source_languages and source_languages != "all" and lang_dir not in source_languages:
            continue
            
        jsonl_path = os.path.join(lang_path, f"{lang_dir}.jsonl")
        if not os.path.exists(jsonl_path):
            continue
            
        logger.info(f"Processing source language: {lang_dir}")
        count = 0
        
        # 使用临时文件进行原地更新
        tmp_jsonl_path = jsonl_path + ".tmp"
        
        with open(jsonl_path, "r", encoding="utf-8") as f_in, \
             open(tmp_jsonl_path, "w", encoding="utf-8") as f_out:
            
            for line in f_in:
                if not line.strip():
                    continue
                    
                try:
                    data = json.loads(line)
                    
                    # 确保拥有 original_language
                    if "original_language" not in data:
                        data["original_language"] = data.get("language", lang_dir)
                        
                    source_lang = data["original_language"]
                    source_text = data.get("content", "")
                    
                    if not source_text:
                        f_out.write(json.dumps(data, ensure_ascii=False) + "\n")
                        continue
                        
                    # 获取已经翻译过的语言列表
                    translated_list = data.get("translated", [])
                    if not isinstance(translated_list, list):
                        translated_list = []
                        
                    # 判断是否还需要翻译当前条目
                    need_translation = False
                    if max_items == 0 or count < max_items:
                        need_translation = True
                        
                    if need_translation:
                        for target_lang in target_languages:
                            if target_lang == source_lang or target_lang in translated_list:
                                continue
                                
                            logger.info(f"Translating item {count+1} from {source_lang} to {target_lang}...")
                            
                            translated_text = translate_long_text(translator, source_text, source_lang, target_lang)
                            if translated_text:
                                data[f"content_{target_lang}"] = translated_text
                                translated_list.append(target_lang)
                        
                        count += 1
                        
                    data["translated"] = translated_list
                    
                    # 写入更新后的数据
                    f_out.write(json.dumps(data, ensure_ascii=False) + "\n")
                    
                except Exception as e:
                    logger.error(f"Error processing item: {e}")
                    # 如果解析失败或者报错，保留原始数据
                    f_out.write(line)
                    
        # 替换原文件
        shutil.move(tmp_jsonl_path, jsonl_path)
        logger.info(f"Updated {jsonl_path} successfully.")

if __name__ == "__main__":
    main()
