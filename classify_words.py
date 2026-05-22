import os
import re
import sys
import json
import argparse
import requests

try:
    from llm_rotator import LLMRotator
except ImportError:
    LLMRotator = None

# Default paths relative to script location
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_INPUT = os.path.join(SCRIPT_DIR, "base_of_word", "Word.v.10.sql")
DEFAULT_OUTPUT = os.path.join(SCRIPT_DIR, "base_of_word", "Word.v.10.level.sql")
DEFAULT_CACHE = os.path.join(SCRIPT_DIR, "classification_cache.json")

# Mapping of Ukrainian months/other lists if needed, but not relevant here.
# Heuristic mappings
KNOWN_LEVEL_WORDS = {
    # 10. Абсолют
    "буття": 10, "всесвіт": 10, "космос": 10, "універсум": 10, "абсолют": 10, "ніщо": 10, "існування": 10,
    
    # 9. Сутність / Концепт
    "кохання": 9, "час": 9, "простір": 9, "число": 9, "ідея": 9, "думка": 9, "розум": 9, 
    "теорія": 9, "концепт": 9, "категорія": 9, "філософія": 9, "наука": 9, "інформація": 9,
    "доля": 9, "свобода": 9, "правда": 9, "істина": 9, "закон": 9, "душа": 9, "мислення": 9,

    # 8. Матеріальність / Тіло
    "матерія": 8, "речовина": 8, "тіло": 8, "вода": 8, "газ": 8, "метал": 8, "камінь": 8, 
    "світло": 8, "атом": 8, "молекула": 8, "об'єкт": 8, "об`єкт": 8, "пісок": 8, "повітря": 8,
    "земля": 8, "вогонь": 8, "деревина": 8, "пластик": 8, "рідина": 8, "електрика": 8,

    # 7. Походження (Артефакт / Натуралія)
    "артефакт": 7, "природа": 7, "організм": 7, "тварина": 7, "рослина": 7, "виріб": 7, 
    "предмет": 7, "інструмент": 7, "дерево": 7, "квітка": 7, "звір": 7, "птах": 7, "риба": 7,

    # 6. Призначення / Роль (Сфера життя)
    "транспорт": 6, "меблі": 6, "одяг": 6, "їжа": 6, "будівля": 6, "посуд": 6, "зброя": 6, 
    "житло": 6, "апаратура": 6, "взуття": 6, "напій": 6, "ліки": 6,

    # 5. Категорія / Кластер
    "стілець": 5, "стіл": 5, "шафа": 5, "ліжко": 5, "куртка": 5, "черевик": 5, "тарілка": 5, 
    "автомобіль": 5, "літак": 5, "будинок": 5, "телефон": 5, "комп'ютер": 5, "комп`ютер": 5,
    "ніж": 5, "вилка": 5, "чашка": 5, "ложка": 5, "чоботи": 5, "пальто": 5, "штани": 5,
    "автобус": 5, "поїзд": 5,
}

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

def get_canonical_score(part_of_language, number, kind, genus, is_infinitive, is_main):
    part_lower = str(part_of_language or '').lower().strip()
    case_lower = str(kind or '').lower().strip()
    num_lower = str(number or '').lower().strip()
    gen_lower = str(genus or '').lower().strip()
    
    try:
        is_inf = int(is_infinitive) if is_infinitive is not None else 0
    except (ValueError, TypeError):
        is_inf = 0
        
    try:
        is_main_val = int(is_main) if is_main is not None else 0
    except (ValueError, TypeError):
        is_main_val = 0

    # We prefer is_main_form = 1
    main_penalty = 0 if is_main_val == 1 else 1

    # Define grammatical penalty based on part of speech
    gram_penalty = 99
    
    # Nouns & Proper Names
    if part_lower in ('іменник', 'іменники', 'чоловіче ім`я', 'жіноче ім`я', 'чоловіче ім\'я', 'жіноче ім\'я'):
        if num_lower == 'однина' and case_lower == 'називний':
            gram_penalty = 0
        elif num_lower == 'множина' and case_lower == 'називний':
            gram_penalty = 1
        elif case_lower == 'називний':
            gram_penalty = 2
        elif num_lower == 'однина':
            gram_penalty = 3
        else:
            gram_penalty = 4
            
    # Adjectives
    elif 'прикметник' in part_lower:
        if num_lower == 'однина' and gen_lower == 'чоловічий' and case_lower == 'називний':
            gram_penalty = 0
        elif num_lower == 'однина' and case_lower == 'називний':
            gram_penalty = 1
        elif gen_lower == 'чоловічий' and case_lower == 'називний':
            gram_penalty = 2
        elif case_lower == 'називний':
            gram_penalty = 3
        elif num_lower == 'однина' and gen_lower == 'чоловічий':
            gram_penalty = 4
        else:
            gram_penalty = 5
            
    # Verbs
    elif 'дієслово' in part_lower:
        if is_inf == 1:
            gram_penalty = 0
        else:
            gram_penalty = 1
            
    # Other parts of speech
    else:
        if is_main_val == 1:
            gram_penalty = 0
        else:
            gram_penalty = 1
            
    return (main_penalty, gram_penalty)


def classify_heuristics(word, part_of_language, creature, genus, number):
    """
    Applies heuristic rules based on grammatical features and lists.
    Returns level (1-10) or None if inconclusive.
    """
    word_lower = word.lower().strip()
    
    # Rule 1: Names (Proper Nouns) -> Level 1 (Одиниця)
    if part_of_language in ('чоловіче ім`я', 'жіноче ім`я', 'чоловіче ім\'я', 'жіноче ім\'я'):
        return 1
        
    # Rule 2: Service/grammar parts of speech -> Level 9 (Сутність) or 10
    if part_of_language in ('сполучник', 'прийменник', 'частка', 'вигук', 'вставне слово'):
        if word_lower in ('є', 'існувати', 'бути', 'усе', 'все', 'ніщо', 'всесвіт', 'космос', 'небо'):
            return 10
        return 9
        
    # Rule 3: Pronouns -> Level 9 (Concept of pointing) or Level 1 (Indexical pointing)
    if part_of_language == 'займенник':
        if word_lower in ('це', 'цей', 'ця', 'це', 'ті', 'той', 'та', 'он', 'от'):
            return 1  # Points to a specific individual entity
        return 9
        
    # Rule 4: Numerals -> Level 9 (Mathematical concept)
    if part_of_language == 'числівник':
        return 9
        
    # Rule 5: Specific known vocabularies
    if word_lower in KNOWN_LEVEL_WORDS:
        return KNOWN_LEVEL_WORDS[word_lower]
        
    # Rule 6: Animate nouns that are not names (e.g., 'кіт', 'собака', 'людина') -> Level 7 (Naturalia/Organisms)
    if part_of_language == 'іменник' and creature == 'істота':
        # E.g., 'людина', 'кіт', 'риба' are living creatures -> Level 7
        return 7
        
    return None

def query_llm_batch(words_to_query, api_type, api_key, model_name=None):
    """
    Classifies a list of words using an LLM.
    Returns a dict {word: level} or empty dict on failure.
    """
    if not words_to_query:
        return {}
        
    print(f"🤖 Querying LLM for {len(words_to_query)} words...")
    
    # Construct prompt
    prompt = (
        "Класифікуй вказані українські слова за шкалою рівня абстракції від 1 до 10, "
        "де кожне нижче поняття є частиною вищого (як матрьошка):\n"
        "10 - Абсолют/Буття (всесвіт, космос, буття, ніщо, існувати)\n"
        "9 - Сутність/Концепт (абстрактні ідеї: час, любов, число, ідея, категорія, прикметники)\n"
        "8 - Матеріальність/Тіло (речовини, фізичні тіла: вода, metal, камінь, об'єкт)\n"
        "7 - Походження (біологічні організми, природні чи штучні загальні класи: природа, тварина, рослина, виріб, інструмент, файл, програма)\n"
        "6 - Призначення/Роль (сфери людського вжитку: транспорт, меблі, одяг, їжа, посуд)\n"
        "5 - Категорія/Кластер (конкретні групи предметів: стілець, стіл, куртка, тарілка, автомобіль, будинок)\n"
        "4 - Рід/Гіперонім (клас конкретного предмета: письмовий стіл, кухонний стіл, легковий автомобіль)\n"
        "3 - Вид/Гіпонім (специфічна версія предмета: парта, пуховик, позашляховик)\n"
        "2 - Модель/Варіація (конкретна лінійка, серія, бренд: Corolla, iPhone, модель БЕКРАНТ)\n"
        "1 - Одиниця/Індивід (унікальний фізичний об'єкт у реальному світі або власне ім'я: Київ, Сонце, Шевченко)\n\n"
        "Для кожного слова виведи ТІЛЬКИ слово і відповідну цифру через двокрапку. Не пиши жодних інших пояснень.\n"
        "Формат виводу:\n"
        "слово: цифра\n"
        "слово: цифра\n\n"
        "Слова для класифікації:\n"
    )
    for word, part in words_to_query:
        prompt += f"- {word} (частина мови: {part})\n"
        
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
            
        elif api_type == 'gemini':
            # Gemini API direct endpoint
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
            # OpenAI API endpoint
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
            # Ollama local endpoint
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
            
        # Parse lines like "стіл: 5"
        for line in response_text.strip().split('\n'):
            line = line.strip().lstrip('-').strip()
            if ':' in line:
                parts = line.split(':')
                w = parts[0].strip().lower()
                try:
                    lvl = int(re.sub(r'\D', '', parts[1].strip()))
                    if 1 <= lvl <= 10:
                        results[w] = lvl
                except Exception:
                    pass
                    
    except Exception as e:
        print(f"⚠️ Error calling LLM: {e}")
        
    return results

# Main classification controller (using two-pass architecture)
import time

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
            json.dump(data, f, ensure_ascii=False)
    except Exception as e:
        print(f"⚠️ Error writing progress file: {e}")

# Main classification controller (using two-pass architecture)
def classify_words_two_pass(input_path, output_path, cache_path, api_type, api_key, model_name, heuristics_only, limit_rows, progress_file=None):
    cache = load_cache(cache_path)
    
    print(f"🔍 PASS 1: Scanning {input_path} for best canonical forms...")
    if not os.path.exists(input_path):
        print(f"❌ Input file not found: {input_path}")
        write_progress(progress_file, "error", 0, 0, f"Error: Input file not found: {input_path}")
        sys.exit(1)
        
    column_index_map = {}
    main_candidates = {} # map: main_form_code -> (score, word, part_of_language, creature, genus, number)
    
    # Pre-count lines to show accurate scan progress
    total_lines = 0
    try:
        with open(input_path, "r", encoding="utf-8") as f:
            for _ in f:
                total_lines += 1
    except Exception:
        pass

    line_idx = 0
    total_val_rows = 0
    
    with open(input_path, "r", encoding="utf-8") as f:
        for line in f:
            line_idx += 1
            if line_idx % 10000 == 0:
                write_progress(progress_file, "scan", line_idx, total_lines, f"Сканування файлу: рядок {line_idx:,} з {total_lines:,}...")
                
            if line.strip().startswith("INSERT INTO `word`"):
                cols_match = re.search(r'\((.*?)\)', line)
                if cols_match:
                    cols_str = cols_match.group(1)
                    cols = [c.strip('` ') for c in cols_str.split(',')]
                    column_index_map = {col: idx for idx, col in enumerate(cols)}
                continue
                
            if line.strip().startswith("(") and column_index_map:
                total_val_rows += 1
                try:
                    vals = parse_sql_values_row(line.strip())
                    if len(vals) < len(column_index_map):
                        continue
                        
                    is_main = int(vals[column_index_map['is_main_form']])
                    main_code = vals[column_index_map['main_form_code']]
                    
                    word = vals[column_index_map['word']]
                    part = vals[column_index_map['part_of_language']]
                    creature = vals[column_index_map['creature']]
                    genus = vals[column_index_map['genus']]
                    number = vals[column_index_map['number']]
                    kind = vals[column_index_map.get('kind')] if 'kind' in column_index_map else '-'
                    is_inf = vals[column_index_map.get('is_infinitive')] if 'is_infinitive' in column_index_map else 0
                    
                    score = get_canonical_score(part, number, kind, genus, is_inf, is_main)
                    
                    # Update candidate if it's the first or has a better canonical score
                    if main_code not in main_candidates or score < main_candidates[main_code][0]:
                        main_candidates[main_code] = (score, word, part, creature, genus, number)
                            
                except Exception:
                    continue
                    
    # Now process selected candidates (heuristics or queue for LLM)
    main_forms_to_classify = {}
    for main_code, (score, word, part, creature, genus, number) in main_candidates.items():
        if main_code in cache:
            continue
            
        level = classify_heuristics(word, part, creature, genus, number)
        if level is not None:
            cache[main_code] = level
        else:
            main_forms_to_classify[main_code] = (word, part)
            
    print(f"ℹ️ Found {len(main_forms_to_classify)} main forms needing LLM classification.")
    write_progress(progress_file, "heuristics", len(cache), len(cache) + len(main_forms_to_classify), f"Застосовано евристики. Знайдено {len(main_forms_to_classify)} лемм для класифікації ШІ.")
    
    # Save heuristics progress to cache
    save_cache(cache, cache_path)
    
    # PASS 1.5: Query LLM for remaining main forms in batches
    if main_forms_to_classify and not heuristics_only and (api_key or api_type in ('ollama', 'rotator')):
        batch_size = 50
        items = list(main_forms_to_classify.items())
        total_to_query = len(items)
        
        for i in range(0, total_to_query, batch_size):
            batch = items[i:i+batch_size]
            words_batch = [(word, part) for code, (word, part) in batch]
            
            write_progress(
                progress_file, 
                "llm", 
                i, 
                total_to_query, 
                f"Запит ШІ: пакет {i//batch_size + 1} з {(total_to_query+batch_size-1)//batch_size} (оброблено лемм: {i}/{total_to_query})..."
            )
            
            llm_results = query_llm_batch(words_batch, api_type, api_key, model_name)
            
            # Save results back to cache
            for code, (word, part) in batch:
                w_lower = word.lower().strip()
                if w_lower in llm_results:
                    cache[code] = llm_results[w_lower]
                else:
                    # Fallback default if LLM failed to classify
                    cache[code] = 9 if part in ('прикметник', 'дієслово', 'прислівник') else 7
                    
            # Intermediate cache save
            save_cache(cache, cache_path)
            
        write_progress(progress_file, "llm", total_to_query, total_to_query, "Класифікацію через ШІ закінчено.")
            
    # PASS 2: Write the output file, adding abstraction_level
    print(f"✍️ PASS 2: Writing structured output to {output_path}...")
    column_index_map = {}
    created_at_idx = -1
    
    words_processed = 0
    words_repaired = 0
    inside_word_create_table = False
    
    # Respect limit for total val rows if present
    target_total = min(total_val_rows, limit_rows) if limit_rows else total_val_rows
    
    with open(input_path, "r", encoding="utf-8") as infile, \
         open(output_path, "w", encoding="utf-8") as outfile:
             
        for line in infile:
            # Track if we are inside the CREATE TABLE block for table `word`
            if "CREATE TABLE" in line and "`word`" in line:
                inside_word_create_table = True
                outfile.write(line)
                continue
                
            if inside_word_create_table:
                if line.strip().startswith(")") or "ENGINE=" in line:
                    inside_word_create_table = False
                    
                if "`created_at` datetime NOT NULL" in line and "abstraction_level" not in line:
                    indent = len(line) - len(line.lstrip())
                    outfile.write(" " * indent + "`abstraction_level` tinyint(4) DEFAULT NULL COMMENT 'Рівень abstraction від 1 до 10',\n")
                    
                outfile.write(line)
                continue
                
            # INSERT header modification
            if line.strip().startswith("INSERT INTO `word`"):
                cols_match = re.search(r'\((.*?)\)', line)
                if cols_match:
                    cols_str = cols_match.group(1)
                    cols = [c.strip('` ') for c in cols_str.split(',')]
                    column_index_map = {col: idx for idx, col in enumerate(cols)}
                    
                    if 'created_at' in column_index_map:
                        created_at_idx = column_index_map['created_at']
                        new_cols = cols.copy()
                        new_cols.insert(created_at_idx, 'abstraction_level')
                        new_cols_str = ", ".join(f"`{c}`" for c in new_cols)
                        
                        modified_line = line.replace(f"({cols_str})", f"({new_cols_str})")
                        outfile.write(modified_line)
                    else:
                        outfile.write(line)
                else:
                    outfile.write(line)
                continue
                
            # VALUES rows modification
            if line.strip().startswith("(") and column_index_map:
                row_str = line.strip()
                ends_with_comma = row_str.endswith(',')
                ends_with_semicolon = row_str.endswith(';')
                
                try:
                    vals = parse_sql_values_row(row_str)
                    if len(vals) >= len(column_index_map) and 'main_form_code' in column_index_map:
                        main_code = vals[column_index_map['main_form_code']]
                        part = vals[column_index_map['part_of_language']]
                        
                        # Get level from cache or fallback
                        level = cache.get(main_code)
                        if level is None:
                            # Fallback if somehow not classified
                            level = 9 if part in ('прикметник', 'дієслово', 'прислівник') else 7
                            
                        # Insert level before created_at
                        if created_at_idx != -1:
                            vals.insert(created_at_idx, level)
                            
                        rebuilt = rebuild_row(vals)
                        # Append ending character
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
                        words_repaired += 1
                        
                        if words_processed % 5000 == 0:
                            write_progress(
                                progress_file, 
                                "write", 
                                words_processed, 
                                target_total, 
                                f"Запис результатів: {words_processed:,} з {target_total:,} слів записано..."
                            )
                            
                        if limit_rows and words_processed >= limit_rows:
                            # Finish current statement with semicolon if we stop early
                            if ends_with_comma:
                                outfile.write(";\n")
                            break
                        continue
                except Exception as e:
                    # On error, write original line
                    outfile.write(line)
                    continue
                    
            # For comments or other non-value lines
            outfile.write(line)
            
    print(f"✨ Successfully finished. Processed {words_processed} words.")
    save_cache(cache, cache_path)
    write_progress(
        progress_file, 
        "done", 
        words_processed, 
        target_total, 
        f"Успішно завершено! Оброблено слів: {words_processed:,}", 
        stats={"cache_size": len(cache)}
    )

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Classify words from SQL dump by abstraction levels.")
    parser.add_argument("--input", default=DEFAULT_INPUT, help="Path to input SQL file")
    parser.add_argument("--output", default=DEFAULT_OUTPUT, help="Path to output SQL file")
    parser.add_argument("--cache", default=DEFAULT_CACHE, help="Path to JSON cache file")
    parser.add_argument("--api-type", choices=['gemini', 'openai', 'ollama', 'rotator'], default='gemini', help="Type of LLM API to use")
    parser.add_argument("--api-key", help="API key for Gemini or OpenAI (falls back to ENV vars)")
    parser.add_argument("--model", help="Model name (e.g. gemini-2.5-flash or gpt-4o-mini)")
    parser.add_argument("--heuristics-only", action="store_true", help="Use only heuristics and skip LLM calls")
    parser.add_argument("--limit", type=int, help="Limit number of rows processed (useful for tests)")
    parser.add_argument("--progress-file", help="Path to JSON progress file for dashboard integration")
    
    args = parser.parse_args()
    
    # Resolve API Key
    api_key = args.api_key
    if not api_key:
        if args.api_type == 'gemini':
            api_key = os.environ.get("GEMINI_API_KEY")
        elif args.api_type == 'openai':
            api_key = os.environ.get("OPENAI_API_KEY")
            
    if not api_key and not args.heuristics_only and args.api_type not in ('ollama', 'rotator'):
        print("⚠️ No API key provided or found in environment variables. Running in heuristics-only mode.")
        args.heuristics_only = True
        
    classify_words_two_pass(
        input_path=args.input,
        output_path=args.output,
        cache_path=args.cache,
        api_type=args.api_type,
        api_key=api_key,
        model_name=args.model,
        heuristics_only=args.heuristics_only,
        limit_rows=args.limit,
        progress_file=args.progress_file
    )
