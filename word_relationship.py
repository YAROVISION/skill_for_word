import os
import re
import sys
import json
import time
import argparse
import difflib

def write_progress(progress_file, phase, current, total, status, stats=None):
    if not progress_file:
        return
    try:
        dir_path = os.path.dirname(os.path.abspath(progress_file))
        os.makedirs(dir_path, exist_ok=True)
        data = {
            "phase": phase,
            "current": current,
            "total": total,
            "status": status,
            "timestamp": time.time(),
            "stats": stats or {}
        }
        with open(progress_file, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"⚠️ Error writing progress file: {e}")

try:
    from llm_rotator import LLMRotator
except ImportError:
    LLMRotator = None

# Default paths relative to script location
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_INPUT = os.path.join(SCRIPT_DIR, "base_of_word", "Word.v.10.level.sql")
DEFAULT_OUTPUT = os.path.join(SCRIPT_DIR, "base_of_word", "Word.v.10.level.relationship.sql")
DEFAULT_CACHE = os.path.join(SCRIPT_DIR, "relationship_cache.json")

def load_cache(cache_path):
    if os.path.exists(cache_path):
        try:
            with open(cache_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            print(f"⚠️ Error loading cache: {e}. Starting with empty cache.")
    return {}

def save_cache(cache, cache_path):
    try:
        with open(cache_path, "w", encoding="utf-8") as f:
            json.dump(cache, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"⚠️ Error saving cache: {e}")

def parse_sql_values_row(val_str):
    """
    Parses a single row of values from an INSERT statement, e.g.:
    (548920, 'iз', 'iз', '...', 338274, ...)
    """
    vals = []
    i = 0
    val_str = val_str.strip()
    
    # Strip wrapping parenthesis if present
    if val_str.startswith('('):
        val_str = val_str[1:]
    if val_str.endswith('),'):
        val_str = val_str[:-2]
    elif val_str.endswith(');'):
        val_str = val_str[:-2]
    elif val_str.endswith(')'):
        val_str = val_str[:-1]
        
    n = len(val_str)
    while i < n:
        # Skip whitespaces and commas
        while i < n and (val_str[i].isspace() or val_str[i] == ','):
            i += 1
        if i >= n:
            break
        
        if val_str[i] == "'":
            # Parse string literal
            i += 1  # consume opening quote
            str_val = []
            while i < n:
                if val_str[i] == "'" and (i + 1 >= n or val_str[i+1] != "'"):
                    i += 1  # consume closing quote
                    break
                elif val_str[i] == "'" and i + 1 < n and val_str[i+1] == "'":
                    str_val.append("'")
                    i += 2
                elif val_str[i] == '\\':
                    if i + 1 < n:
                        str_val.append(val_str[i+1])
                        i += 2
                    else:
                        str_val.append('\\')
                        i += 1
                else:
                    str_val.append(val_str[i])
                    i += 1
            vals.append("".join(str_val))
        elif val_str[i:i+4].upper() == 'NULL':
            vals.append(None)
            i += 4
        else:
            # Parse number or other unquoted tokens
            start = i
            while i < n and val_str[i] != ',' and not val_str[i].isspace() and val_str[i] != ')':
                i += 1
            token = val_str[start:i]
            if '.' in token:
                try:
                    vals.append(float(token))
                except ValueError:
                    vals.append(token)
            else:
                try:
                    vals.append(int(token))
                except ValueError:
                    vals.append(token)
    return vals

def format_sql_value(val):
    if val is None:
        return 'NULL'
    elif isinstance(val, (int, float)):
        return str(val)
    else:
        # Escape string literal
        escaped = val.replace('\\', '\\\\').replace("'", "''")
        return f"'{escaped}'"

def rebuild_row(vals):
    return "(" + ", ".join(format_sql_value(v) for v in vals) + ")"

def query_llm_relationship_batch(child_batch, parent_candidates, api_type, api_key, model_name=None):
    """
    Asks the LLM to map each child word in the batch to the most logical parent candidate.
    """
    if not child_batch or not parent_candidates:
        return {}
        
    # Prepare parent candidates text
    parent_list_str = "\n".join(f"- {word} (код леми: {code}, част. мови: {part})" for code, word, part in parent_candidates)
    
    # Prepare children list text
    children_list_str = "\n".join(f"- {word} (код леми: {code}, част. мови: {part})" for code, word, part in child_batch)
    
    prompt = (
        "Ти — лінгвістичний асистент. Твоє завдання — побудувати ієрархічні зв'язки між словами.\n"
        "Для кожного слова з першого списку (діти) вибери найбільш логічне батьківське слово (ширше поняття, гіперонім) "
        "з другого списку (дозволені кандидати на роль батька).\n\n"
        
        "Ось СПИСОК ДОЗВОЛЕНИХ КАНДИДАТІВ НА РОЛЬ БАТЬКА (вибирай ТІЛЬКИ з цих слів):\n"
        f"{parent_list_str}\n\n"
        
        "Ось СПИСОК СЛІВ ДЛЯ ЗВ'ЯЗУВАННЯ (ДІТИ):\n"
        f"{children_list_str}\n\n"
        
        "Для кожного слова з першого списку визнач найкращого батька зі списку дозволених кандидатів.\n"
        "Якщо жодне слово не підходить ідеально за смислом, вибери найбільш наближене за значенням або узагальнене "
        "(наприклад, якщо дитина є предметом, а серед батьків є 'об'єкт' чи 'тіло', вибирай його).\n\n"
        
        "Результат виведи ТІЛЬКИ у такому форматі (без будь-якого вступного тексту чи пояснень):\n"
        "код_леми_дитини: код_леми_батька\n"
        "код_леми_дитини: код_леми_батька\n\n"
        
        "Приклад:\n"
        "a394641: a15302\n"
        "a140895: a8025\n"
    )
    
    results = {}
    
    try:
        if api_type == 'rotator':
            if not LLMRotator:
                print("⚠️ LLMRotator class could not be imported.")
                return {}
            rotator = LLMRotator()
            response_text = rotator.chat_completion(
                [{"role": "user", "content": prompt}],
                preferred_provider=model_name
            )
        else:
            # Fallback to standard HTTP requests if rotator is not used
            import requests
            if api_type == 'gemini':
                model = model_name or "gemini-2.5-flash"
                url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
                headers = {"Content-Type": "application/json"}
                payload = {
                    "contents": [{
                        "parts": [{"text": prompt}]
                    }]
                }
                response = requests.post(url, headers=headers, json=payload, timeout=30)
                response.raise_for_status()
                res_json = response.json()
                response_text = res_json['candidates'][0]['content']['parts'][0]['text']
            elif api_type == 'openai':
                model = model_name or "gpt-4o-mini"
                url = "https://api.openai.com/v1/chat/completions"
                headers = {
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {api_key}"
                }
                payload = {
                    "model": model,
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": 0.0
                }
                response = requests.post(url, headers=headers, json=payload, timeout=30)
                response.raise_for_status()
                res_json = response.json()
                response_text = res_json['choices'][0]['message']['content']
            elif api_type == 'ollama':
                model = model_name or "llama3"
                url = "http://localhost:11434/api/generate"
                payload = {
                    "model": model,
                    "prompt": prompt,
                    "stream": False,
                    "options": {"temperature": 0.0}
                }
                response = requests.post(url, json=payload, timeout=60)
                response.raise_for_status()
                res_json = response.json()
                response_text = res_json['response']
            else:
                return {}
                
        # Parse lines like "a394641: a15302"
        valid_parent_codes = {code for code, _, _ in parent_candidates}
        valid_child_codes = {code for code, _, _ in child_batch}
        
        for line in response_text.strip().split('\n'):
            line = line.strip().lstrip('-').strip()
            if ':' in line:
                parts = line.split(':')
                child_code = parts[0].strip()
                parent_code = parts[1].strip()
                
                # Strip potential markdown formatting or quotes
                child_code = re.sub(r'[`\'\"\s]', '', child_code)
                parent_code = re.sub(r'[`\'\"\s]', '', parent_code)
                
                if child_code in valid_child_codes:
                    if parent_code in valid_parent_codes:
                        results[child_code] = parent_code
                        
    except Exception as e:
        print(f"⚠️ Error calling LLM: {e}")
        
    return results

def process_relationships(input_path, output_path, cache_path, api_type, api_key, model_name, limit_rows, progress_file=None):
    cache = load_cache(cache_path)
    
    write_progress(progress_file, "scan", 0, 100, "🔍 Аналіз структури SQL та збір лемм...")
    print(f"🔍 PASS 1: Analyzing database structures and gathering lemmas...")
    if not os.path.exists(input_path):
        write_progress(progress_file, "error", 0, 100, f"❌ Вхідний файл не знайдено: {input_path}")
        print(f"❌ Input file not found: {input_path}")
        sys.exit(1)
        
    column_index_map = {}
    
    # lemma_map: main_form_code -> { 'id': int, 'word': str, 'part': str, 'level': int, 'creature': str }
    lemma_map = {}
    
    line_idx = 0
    
    with open(input_path, "r", encoding="utf-8") as f:
        for line in f:
            line_idx += 1
            if line.strip().startswith("INSERT INTO `word`"):
                cols_match = re.search(r'\((.*?)\)', line)
                if cols_match:
                    cols_str = cols_match.group(1)
                    cols = [c.strip('` ') for c in cols_str.split(',')]
                    column_index_map = {col: idx for idx, col in enumerate(cols)}
                continue
                
            if line.strip().startswith("(") and column_index_map:
                try:
                    vals = parse_sql_values_row(line.strip())
                    if len(vals) < len(column_index_map):
                        continue
                        
                    is_main = int(vals[column_index_map['is_main_form']])
                    main_code = vals[column_index_map['main_form_code']]
                    word = vals[column_index_map['word']]
                    part = vals[column_index_map['part_of_language']]
                    level = int(vals[column_index_map['abstraction_level']])
                    row_id = int(vals[column_index_map['id']])
                    creature = vals[column_index_map['creature']] if 'creature' in column_index_map else '-'
                    
                    if is_main == 1 or main_code not in lemma_map:
                        if main_code not in lemma_map or is_main == 1:
                            lemma_map[main_code] = {
                                'id': row_id,
                                'word': word,
                                'part': part,
                                'level': level,
                                'creature': creature
                            }
                            
                except Exception:
                    continue
                    
    print(f"ℹ️ Total unique lemmas found: {len(lemma_map)}")
    
    # Group lemmas by level
    lemmas_by_level = {}
    for code, info in lemma_map.items():
        lvl = info['level']
        if lvl not in lemmas_by_level:
            lemmas_by_level[lvl] = []
        lemmas_by_level[lvl].append((code, info['word'], info['part']))
        
    active_levels = sorted(lemmas_by_level.keys(), reverse=True)
    print(f"ℹ️ Active levels present in data: {active_levels}")
    
    # Build relationships level by level (from top down)
    total_steps = len(active_levels) - 1
    for idx in range(1, len(active_levels)):
        parent_lvl = active_levels[idx - 1]
        child_lvl = active_levels[idx]
        
        children = lemmas_by_level[child_lvl]
        parents = lemmas_by_level[parent_lvl]
        
        needed_children = [c for c in children if c[0] not in cache]
        
        write_progress(
            progress_file, 
            "mapping", 
            idx - 1, 
            total_steps, 
            f"🔗 Зв'язування рівнів: Рівень {child_lvl} -> Рівень {parent_lvl}... (Залишилося: {len(needed_children)} лемм)",
            {"total_lemmas": len(lemma_map)}
        )
        
        print(f"🔗 Mapping Level {child_lvl} -> Level {parent_lvl}: {len(needed_children)} lemmas need mapping (out of {len(children)} total).")
        
        if not needed_children:
            continue
            
        # Fast Heuristics for Level 9 -> Level 10
        if child_lvl == 9 and parent_lvl == 10:
            print(f"⚡ Applying heuristics for Level 9 -> Level 10 ({len(needed_children)} lemmas)...")
            parent_by_name = {word.lower(): code for code, word, part in parents}
            for code, word, part in needed_children:
                word_lower = word.lower().strip()
                part_lower = str(part or '').lower().strip()
                
                if any(x in word_lower for x in ('всесвіт', 'космос', 'галактик', 'зорян', 'планет', 'небес', 'сонц', 'косміч')):
                    parent_word = 'всесвіт' if 'всесвіт' in parent_by_name else 'космос'
                elif 'дієслово' in part_lower or 'дієприкметник' in part_lower or 'дієприслівник' in part_lower:
                    parent_word = 'існування' if 'існування' in parent_by_name else 'буття'
                else:
                    parent_word = 'буття'
                    
                cache[code] = parent_by_name.get(parent_word, parents[0][0])
            save_cache(cache, cache_path)
            continue
            
        # Fast Heuristics for Level 7 -> Level 8
        elif child_lvl == 7 and parent_lvl == 8:
            print(f"⚡ Applying heuristics for Level 7 -> Level 8 ({len(needed_children)} lemmas)...")
            parent_by_name = {word.lower(): code for code, word, part in parents}
            
            for code, word, part in needed_children:
                word_lower = word.lower().strip()
                info = lemma_map[code]
                creature = str(info.get('creature', '')).lower().strip()
                
                parent_word = 'матерія' # default
                
                if 'істота' in creature:
                    parent_word = 'тіло'
                elif any(x in word_lower for x in ('дерево', 'кущ', 'квітка', 'трава', 'листя', 'хвоя', 'рослин', 'ліс', 'гілк')):
                    parent_word = 'деревина' if 'деревина' in parent_by_name else 'тіло'
                elif any(x in word_lower for x in ('світло', 'промінь', 'блиск', 'осяйн', 'лазер', 'фотон')):
                    parent_word = 'світло' if 'світло' in parent_by_name else 'матерія'
                elif any(x in word_lower for x in ('струм', 'напруга', 'електрич', 'заряд', 'струм', 'кабель')):
                    parent_word = 'електрика' if 'електрика' in parent_by_name else 'матерія'
                elif any(x in word_lower for x in ('вітер', 'кисень', 'водень', 'пара', 'газ', 'атмосфер')):
                    parent_word = 'газ' if 'газ' in parent_by_name else 'повітря'
                elif any(x in word_lower for x in ('море', 'океан', 'річка', 'дощ', 'лід', 'крапля', 'вода', 'озер')):
                    parent_word = 'вода'
                elif any(x in word_lower for x in ('граніт', 'цегла', 'руда', 'камін', 'мармур')):
                    parent_word = 'камінь'
                elif any(x in word_lower for x in ('пластик', 'гума', 'полімер', 'нейлон')):
                    parent_word = 'пластик'
                
                if parent_word not in parent_by_name:
                    parent_word = 'матерія' if 'матерія' in parent_by_name else 'тіло'
                    
                cache[code] = parent_by_name.get(parent_word, parents[0][0])
                
            save_cache(cache, cache_path)
            continue
            
        # Standard LLM lookup for other levels (e.g. 8->9, 6->7, 5->6, 1->5)
        batch_size = 50
        total_to_map = len(needed_children)
        
        for i in range(0, total_to_map, batch_size):
            batch = needed_children[i:i+batch_size]
            
            print(f"🤖 Batch {i//batch_size + 1}/{(total_to_map+batch_size-1)//batch_size} (Mapping {len(batch)} words from level {child_lvl} to level {parent_lvl} via LLM)...")
            
            mappings = query_llm_relationship_batch(batch, parents, api_type, api_key, model_name)
            
            # Save mappings to cache
            for child_code, child_word, _ in batch:
                if child_code in mappings:
                    cache[child_code] = mappings[child_code]
                else:
                    # Fallback default
                    if parents:
                        cache[child_code] = parents[0][0]
                    else:
                        cache[child_code] = None
                        
            save_cache(cache, cache_path)
            
    print("✅ All parent-child lemma relationships mapped.")
    
    # PASS 2: Rewrite the SQL file adding parent_id column
    write_progress(progress_file, "write", 0, limit_rows or 405363, "✍️ Запис результатів у новий SQL файл...")
    print(f"✍️ PASS 2: Writing relationships into new SQL file {output_path}...")
    
    parent_db_id_map = {}
    for code, info in lemma_map.items():
        parent_code = cache.get(code)
        if parent_code and parent_code in lemma_map:
            parent_db_id_map[code] = lemma_map[parent_code]['id']
        else:
            parent_db_id_map[code] = None
            
    column_index_map = {}
    created_at_idx = -1
    abstraction_level_idx = -1
    
    words_processed = 0
    inside_word_create_table = False
    
    with open(input_path, "r", encoding="utf-8") as infile, \
         open(output_path, "w", encoding="utf-8") as outfile:
             
        for line in infile:
            if "CREATE TABLE" in line and "`word`" in line:
                inside_word_create_table = True
                outfile.write(line)
                continue
                
            if inside_word_create_table:
                if line.strip().startswith(")") or "ENGINE=" in line:
                    inside_word_create_table = False
                    
                if "`created_at` datetime" in line and "parent_id" not in line:
                    indent = len(line) - len(line.lstrip())
                    outfile.write(" " * indent + "`parent_id` int(11) DEFAULT NULL COMMENT 'ID батьківського слова з вищого рівня абстракції',\n")
                    
                if "KEY `is_main_form`" in line and "parent_id" not in line:
                    stripped_line = line.rstrip('\r\n')
                    if not stripped_line.endswith(','):
                        outfile.write(stripped_line + ",\n")
                        indent = len(line) - len(line.lstrip())
                        outfile.write(" " * indent + "KEY `parent_id` (`parent_id`)\n")
                    else:
                        outfile.write(line)
                        indent = len(line) - len(line.lstrip())
                        outfile.write(" " * indent + "KEY `parent_id` (`parent_id`),\n")
                    continue
                    
                outfile.write(line)
                continue
                
            if line.strip().startswith("INSERT INTO `word`"):
                cols_match = re.search(r'\((.*?)\)', line)
                if cols_match:
                    cols_str = cols_match.group(1)
                    cols = [c.strip('` ') for c in cols_str.split(',')]
                    column_index_map = {col: idx for idx, col in enumerate(cols)}
                    
                    if 'abstraction_level' in column_index_map:
                        abstraction_level_idx = column_index_map['abstraction_level']
                        new_cols = cols.copy()
                        new_cols.insert(abstraction_level_idx + 1, 'parent_id')
                        new_cols_str = ", ".join(f"`{c}`" for c in new_cols)
                        
                        modified_line = line.replace(f"({cols_str})", f"({new_cols_str})")
                        outfile.write(modified_line)
                    else:
                        outfile.write(line)
                else:
                    outfile.write(line)
                continue
                
            if line.strip().startswith("(") and column_index_map:
                row_str = line.strip()
                ends_with_comma = row_str.endswith(',')
                ends_with_semicolon = row_str.endswith(';')
                
                try:
                    vals = parse_sql_values_row(row_str)
                    if len(vals) >= len(column_index_map) and 'main_form_code' in column_index_map:
                        main_code = vals[column_index_map['main_form_code']]
                        parent_id = parent_db_id_map.get(main_code)
                        
                        if abstraction_level_idx != -1:
                            vals.insert(abstraction_level_idx + 1, parent_id)
                            
                        rebuilt = rebuild_row(vals)
                        if ends_with_comma:
                            rebuilt += ",\n"
                        elif ends_with_semicolon:
                            rebuilt += ";\n"
                        else:
                            rebuilt += "\n"
                            
                        indent = len(line) - len(line.lstrip())
                        whitespace = line[:indent]
                        outfile.write(whitespace + rebuilt)
                        words_processed += 1
                        
                        if words_processed % 20000 == 0:
                            write_progress(progress_file, "write", words_processed, limit_rows or 405363, f"✍️ Перезапис: {words_processed:,} слів...")
                            print(f"✍️ Rebuilt {words_processed:,} data rows...")
                            
                        if limit_rows and words_processed >= limit_rows:
                            if ends_with_comma:
                                outfile.write(";\n")
                            break
                        continue
                except Exception as e:
                    outfile.write(line)
                    continue
                    
            outfile.write(line)
            
    write_progress(progress_file, "done", words_processed, words_processed, "✨ Успішно завершено!")
    print(f"✨ Successfully finished. Rebuilt {words_processed:,} data rows.")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Create parent-child relationships between words across levels.")
    parser.add_argument("--input", default=DEFAULT_INPUT, help="Path to input SQL file")
    parser.add_argument("--output", default=DEFAULT_OUTPUT, help="Path to output SQL file")
    parser.add_argument("--cache", default=DEFAULT_CACHE, help="Path to JSON cache file")
    parser.add_argument("--api-type", choices=['gemini', 'openai', 'ollama', 'rotator'], default='rotator', help="Type of LLM API to use")
    parser.add_argument("--api-key", help="API key for Gemini or OpenAI (falls back to ENV vars)")
    parser.add_argument("--model", help="Model name (e.g. gemini-2.5-flash or gpt-4o-mini)")
    parser.add_argument("--limit", type=int, help="Limit number of rows processed (useful for tests)")
    parser.add_argument("--progress-file", help="Path to write progress JSON file")
    
    args = parser.parse_args()
    
    api_key = args.api_key
    if not api_key:
        if args.api_type == 'gemini':
            api_key = os.environ.get("GEMINI_API_KEY")
        elif args.api_type == 'openai':
            api_key = os.environ.get("OPENAI_API_KEY")
            
    process_relationships(
        input_path=args.input,
        output_path=args.output,
        cache_path=args.cache,
        api_type=args.api_type,
        api_key=api_key,
        model_name=args.model,
        limit_rows=args.limit,
        progress_file=args.progress_file
    )
