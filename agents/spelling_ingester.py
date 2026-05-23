import os
import sys
import json
import re
import asyncio
from agents.base import BaseAgent

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PARENT_DIR = os.path.dirname(SCRIPT_DIR)
SCRATCH_DIR = os.path.join(PARENT_DIR, "scratch")

class SpellingIngester(BaseAgent):
    def __init__(self):
        super().__init__(name="SpellingIngester")
        self.existing_words_index_path = os.path.join(SCRATCH_DIR, "existing_words_index.json")

    async def process_user_text(self, text, sql_file="base_of_word/Word.v.10.sql"):
        """
        Main entry point for processing raw user text.
        1. Corrects spelling and extracts unique lemmas.
        2. Checks against database index.
        3. Generates morphological paradigms for missing words.
        4. Appends to SQL.
        5. Returns status report.
        """
        self.log(f"Processing text: '{text[:50]}...'")
        
        # 1. Spelling correction & lemma extraction
        corrected_text, raw_lemmas = await self._correct_and_extract(text)
        if not raw_lemmas:
            return {
                "success": False,
                "error": "Failed to extract words from text.",
                "corrected_text": corrected_text
            }

        # 2. Check existence in DB
        sql_path = os.path.join(PARENT_DIR, sql_file)
        existing_lemmas = self._load_existing_lemmas(sql_path)
        
        missing_lemmas = []
        for item in raw_lemmas:
            word = item["word"].lower().strip()
            pos = item["pos"]
            if word not in existing_lemmas:
                missing_lemmas.append((word, pos))

        self.log(f"Spelling check complete. Found {len(missing_lemmas)} missing words out of {len(raw_lemmas)} unique words.")
        
        if not missing_lemmas:
            return {
                "success": True,
                "corrected_text": corrected_text,
                "added_words": [],
                "msg": "Всі слова з тексту вже присутні в базі даних."
            }

        # 3. Generate paradigms for missing words
        new_records = []
        added_words_list = []
        for word, pos in missing_lemmas:
            paradigm = await self._generate_morphological_paradigm(word, pos)
            if paradigm:
                new_records.append(paradigm)
                added_words_list.append(f"{word} ({pos})")
                
        # 4. Append to SQL
        if new_records:
            self._append_to_sql_file(sql_path, new_records)
            # Rebuild existing index cache
            self._rebuild_index_cache(sql_path)
            
        return {
            "success": True,
            "corrected_text": corrected_text,
            "added_words": added_words_list,
            "msg": f"Успішно імпортовано {len(added_words_list)} нових слів (та їхні форми) до бази даних."
        }

    async def _correct_and_extract(self, text):
        """
        Sends text to LLM to correct spelling and extract lemmas.
        """
        system_prompt = (
            "Ти — професійний лінгвіст української мови. Твоє завдання:\n"
            "1. Виправити граматичні, орфографічні та пунктуаційні помилки в наданому користувачем тексті.\n"
            "2. Виділити всі унікальні повнозначні слова у їхній початковій словниковій формі (леммі) "
            "та визначити їхню частину мови (тільки 'іменник', 'прикметник', 'дієслово', 'прислівник', 'займенник', 'числівник').\n"
            "Поверни результат виключно у форматі JSON без жодного додаткового опису чи розмітки markdown.\n"
            "Формат JSON:\n"
            "{\n"
            "  \"corrected_text\": \"виправлений текст тут\",\n"
            "  \"lemmas\": [\n"
            "    {\"word\": \"слово1\", \"pos\": \"іменник\"},\n"
            "    {\"word\": \"слово2\", \"pos\": \"дієслово\"}\n"
            "  ]\n"
            "}"
        )
        try:
            res_content = self.chat(prompt=text, system_prompt=system_prompt)
            # Clean markdown code block if LLM returned it
            cleaned_json = re.sub(r'^```json\s*|```$', '', res_content.strip(), flags=re.MULTILINE)
            data = json.loads(cleaned_json)
            return data.get("corrected_text", text), data.get("lemmas", [])
        except Exception as e:
            self.log(f"Error correcting spelling: {e}")
            return text, []

    def _load_existing_lemmas(self, sql_path):
        """
        Loads existing lemmas from index cache, or scans SQL file if cache is stale/missing.
        """
        if not os.path.exists(sql_path):
            return set()

        sql_mtime = os.path.getmtime(sql_path)
        
        # Check cache
        if os.path.exists(self.existing_words_index_path):
            try:
                cache_mtime = os.path.getmtime(self.existing_words_index_path)
                if cache_mtime >= sql_mtime:
                    with open(self.existing_words_index_path, "r", encoding="utf-8") as f:
                        return set(json.load(f))
            except Exception:
                pass
                
        # Scan SQL file
        self.log(f"Scanning SQL file {sql_path} to build existing words index...")
        existing = set()
        column_index_map = {}
        
        try:
            with open(sql_path, "r", encoding="utf-8") as f:
                for line in f:
                    if line.strip().startswith("INSERT INTO `word`"):
                        cols_match = re.search(r'\((.*?)\)', line)
                        if cols_match:
                            cols_str = cols_match.group(1)
                            cols = [c.strip('` ') for c in cols_str.split(',')]
                            column_index_map = {col: idx for idx, col in enumerate(cols)}
                        continue
                        
                    if line.strip().startswith("(") and column_index_map:
                        # Extract word value directly to be fast
                        row_str = line.strip()
                        # parse columns roughly using comma split if simple, or full parser
                        # For speed, let's extract values
                        vals = self._quick_parse_row(row_str)
                        if len(vals) > column_index_map.get('word', 1):
                            word_val = vals[column_index_map['word']]
                            is_main = int(vals[column_index_map['is_main_form']]) if column_index_map.get('is_main_form') is not None and vals[column_index_map['is_main_form']] is not None else 1
                            if is_main == 1 and word_val:
                                existing.add(word_val.lower().strip())
        except Exception as e:
            self.log(f"Error scanning SQL: {e}")

        # Save cache
        try:
            os.makedirs(SCRATCH_DIR, exist_ok=True)
            with open(self.existing_words_index_path, "w", encoding="utf-8") as f:
                json.dump(list(existing), f, ensure_ascii=False)
        except Exception as e:
            self.log(f"Error saving index cache: {e}")
            
        return existing

    def _quick_parse_row(self, row_str):
        """
        Quickly parses values from row like (1, 'iз', ...)
        """
        vals = []
        row_str = row_str.strip('(),;')
        # split by comma, ignoring commas in quotes
        # Simple regex split for SQL values
        parts = re.findall(r"'(?:[^'\\]|\\.)*'|\d+|NULL", row_str)
        for p in parts:
            if p == 'NULL':
                vals.append(None)
            elif p.startswith("'") and p.endswith("'"):
                vals.append(p[1:-1].replace("\\'", "'").replace("\\\\", "\\"))
            else:
                try:
                    if '.' in p:
                        vals.append(float(p))
                    else:
                        vals.append(int(p))
                except ValueError:
                    vals.append(p)
        return vals

    def _rebuild_index_cache(self, sql_path):
        """
        Forced rebuild of existing words index.
        """
        if os.path.exists(self.existing_words_index_path):
            try:
                os.remove(self.existing_words_index_path)
            except:
                pass
        self._load_existing_lemmas(sql_path)

    async def _generate_morphological_paradigm(self, word, pos):
        """
        Generates full morphological paradigm for a word and part of speech.
        """
        self.log(f"Generating morphological forms for: '{word}' ({pos})")
        
        # Determine if POS changes
        # Only nouns, adjectives, and verbs change. Others (preposition, adverb, etc.) do not.
        pos_lower = pos.lower().strip()
        is_changeable = pos_lower in ("іменник", "прикметник", "дієслово", "чоловіче ім`я", "жіноче ім`я", "чоловіче ім'я", "жіноче ім'я")
        
        if not is_changeable:
            # Return single form
            return [{
                "word": word,
                "is_main_form": 1,
                "part_of_language": pos,
                "creature": "-",
                "genus": "-",
                "number": "-",
                "person": "-",
                "kind": "-",
                "verb_kind": "-",
                "dievidmina": "-",
                "class": "-",
                "sub_role": "-",
                "comparison": "-",
                "tense": "-",
                "is_infinitive": 0,
                "mood": "-",
                "variation": "-"
            }]

        prompt = (
            f"Для українського слова '{word}' (частина мови: '{pos}') згенеруй повну граматичну парадигму словоформ "
            f"для збереження в базі даних. \n"
            f"Вимоги:\n"
            f"- Якщо це іменник: згенеруй форму в однині та множині для всіх 7 відмінків (називний, родовий, давальний, знахідний, орудний, місцевий, кличний).\n"
            f"- Якщо це прикметник: згенеруй форми для чотирьох родів (чоловічий, жіночий, середній, а також множина) у всіх відмінках.\n"
            f"- Якщо це дієслово: згенеруй інфінітив, форми теперішнього/минулого/майбутнього часу для осіб або родів.\n"
            f"Початкова форма '{word}' повинна бути обов'язково присутньою в списку та мати 'is_main_form': 1. Всі інші форми повинні мати 'is_main_form': 0.\n\n"
            f"Поверни результат виключно у вигляді JSON-масиву об'єктів із такими ключами:\n"
            f"- 'word' (словоформа, наприклад, 'стола')\n"
            f"- 'is_main_form' (1 для головної форми, 0 для інших)\n"
            f"- 'part_of_language' ('{pos}')\n"
            f"- 'creature' ('істота', 'неістота' або '-')\n"
            f"- 'genus' ('чоловічий', 'жіночий', 'середній' або '-')\n"
            f"- 'number' ('однина', 'множина' або '-')\n"
            f"- 'person' ('1 особа', '2 особа', '3 особа' або '-')\n"
            f"- 'kind' (відмінок: 'називний', 'родовий', 'давальний', 'знахідний', 'орудний', 'місцевий', 'кличний' або '-')\n"
            f"- 'verb_kind' (для дієслів: 'доконаний', 'недоконаний' або '-')\n"
            f"- 'dievidmina' ('1 дієвідміна', '2 дієвідміна' або '-')\n"
            f"- 'class', 'sub_role', 'comparison', 'tense' (часи: 'теперішній', 'минулий', 'майбутній' або '-')\n"
            f"- 'is_infinitive' (1 якщо інфінітив дієслова, 0 інакше)\n"
            f"- 'mood' (спосіб), 'variation' (відміна іменника).\n\n"
            f"Не пиши жодних інших пояснень, тільки валідний JSON-масив."
        )

        try:
            res_content = self.chat(prompt=prompt)
            cleaned_json = re.sub(r'^```json\s*|```$', '', res_content.strip(), flags=re.MULTILINE)
            return json.loads(cleaned_json)
        except Exception as e:
            self.log(f"Error generating morphological forms for {word}: {e}")
            return []

    def _append_to_sql_file(self, sql_path, new_words_paradigms):
        """
        Appends the generated paradigms to the target SQL file.
        Dynamically parses columns from the file to match the insert structure.
        """
        if not os.path.exists(sql_path):
            self.log(f"SQL file not found to append: {sql_path}")
            return

        self.log(f"Appending new records to SQL dump: {sql_path}")
        
        # 1. Find max ID and max html_id
        max_id = self._find_max_id(sql_path)
        max_html_id = self._find_max_html_id(sql_path)
        
        # 2. Parse column names from the first INSERT INTO `word` in the file
        column_index_map = {}
        with open(sql_path, "r", encoding="utf-8") as f:
            for line in f:
                if line.strip().startswith("INSERT INTO `word`"):
                    cols_match = re.search(r'\((.*?)\)', line)
                    if cols_match:
                        cols_str = cols_match.group(1)
                        cols = [c.strip('` ') for c in cols_str.split(',')]
                        column_index_map = {col: idx for idx, col in enumerate(cols)}
                        break
                        
        if not column_index_map:
            self.log("⚠️ Could not parse table columns from SQL file.")
            return

        # Prepare SQL insert statements block
        sql_lines = []
        
        current_id = max_id + 1
        current_html_id = max_html_id + 1
        
        for paradigm in new_words_paradigms:
            # Find the main form to get its ID for main_form_code
            main_form = None
            for form in paradigm:
                if form.get("is_main_form") == 1:
                    main_form = form
                    break
            if not main_form:
                main_form = paradigm[0]
                main_form["is_main_form"] = 1
                
            lemma_id = current_id
            main_form_code = f"a{current_html_id}" # Standard code format: a + html_id
            
            # Write forms
            for form in paradigm:
                row_id = current_id
                current_id += 1
                
                row_html_id = current_html_id
                current_html_id += 1
                
                # Build properties dictionary
                props = {
                    "id": row_id,
                    "word": form.get("word", ""),
                    "word_binary": form.get("word", ""),
                    "unique_code": "", # Will build next
                    "html_id": row_html_id,
                    "main_form_code": main_form_code,
                    "is_main_form": form.get("is_main_form", 0),
                    "is_need_processing": 0,
                    "part_of_language": form.get("part_of_language", "-"),
                    "creature": form.get("creature", "-"),
                    "genus": form.get("genus", "-"),
                    "number": form.get("number", "-"),
                    "person": form.get("person", "-"),
                    "kind": form.get("kind", "-"),
                    "verb_kind": form.get("verb_kind", "-"),
                    "dievidmina": form.get("dievidmina", "-"),
                    "class": form.get("class", "-"),
                    "sub_role": form.get("sub_role", "-"),
                    "comparison": form.get("comparison", "-"),
                    "tense": form.get("tense", "-"),
                    "is_infinitive": form.get("is_infinitive", 0),
                    "mood": form.get("mood", "-"),
                    "variation": form.get("variation", "-"),
                    "abstraction_level": None,
                    "parent_id": None,
                    "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                    "updated_at": time.strftime("%Y-%m-%d %H:%M:%S")
                }
                
                # Build unique_code
                props["unique_code"] = (
                    f"{props['word']};{props['main_form_code']};{props['part_of_language']};"
                    f"{props['creature']};{props['genus']};{props['number']};{props['person']};"
                    f"{props['kind']};{props['verb_kind']};{props['dievidmina']};{props['class']};"
                    f"{props['sub_role']};{props['comparison']};{props['tense']};"
                    f"{props['is_infinitive']};{props['mood']};{props['variation']};;{props['is_main_form']}"
                )
                
                # Order values according to column_index_map
                ordered_vals = [None] * len(column_index_map)
                for col, idx in column_index_map.items():
                    ordered_vals[idx] = props.get(col, None)
                    
                # Format row values
                val_strings = []
                for val in ordered_vals:
                    if val is None:
                        val_strings.append("NULL")
                    elif isinstance(val, (int, float)):
                        val_strings.append(str(val))
                    else:
                        escaped = str(val).replace('\\', '\\\\').replace("'", "''")
                        val_strings.append(f"'{escaped}'")
                        
                row_sql = "(" + ", ".join(val_strings) + ")"
                sql_lines.append(row_sql)
                
        if sql_lines:
            # We append the lines to the SQL file. We need to check if the file ends with a semicolon or comma
            # Typically, HeidiSQL dump has MULTIPLE inserts or inserts grouped together.
            # To be safe, we just append a NEW insert statement command for these new values!
            # E.g. INSERT INTO `word` (col1, col2) VALUES (row1), (row2);
            cols_list_str = ", ".join(f"`{col}`" for col in sorted(column_index_map, key=column_index_map.get))
            insert_statement = f"\n\n-- Agents Ingested Words\nINSERT INTO `word` ({cols_list_str}) VALUES\n"
            insert_statement += ",\n".join(sql_lines) + ";\n"
            
            try:
                with open(sql_path, "a", encoding="utf-8") as f:
                    f.write(insert_statement)
                self.log(f"Successfully appended {len(sql_lines)} rows to SQL file.")
            except Exception as e:
                self.log(f"Error appending to SQL file: {e}")

    def _find_max_id(self, file_path):
        """
        Scans SQL file to find maximum ID.
        """
        max_id = 0
        try:
            with open(file_path, "rb") as f:
                f.seek(0, os.SEEK_END)
                size = f.tell()
                chunk_size = min(size, 65536)
                f.seek(size - chunk_size)
                chunk = f.read(chunk_size).decode('utf-8', errors='ignore')
                lines = chunk.split('\n')
                for line in lines:
                    line = line.strip()
                    if line.startswith('('):
                        match = re.match(r'^\(\s*(\d+)', line)
                        if match:
                            val = int(match.group(1))
                            if val > max_id:
                                max_id = val
        except Exception:
            pass
            
        if max_id == 0: # Scan whole file if seek failed
            try:
                with open(file_path, "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if line.startswith('('):
                            match = re.match(r'^\(\s*(\d+)', line)
                            if match:
                                val = int(match.group(1))
                                if val > max_id:
                                    max_id = val
            except Exception:
                pass
        return max_id

    def _find_max_html_id(self, file_path):
        """
        Scans SQL file to find maximum html_id.
        """
        max_html = 0
        column_index_map = {}
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                for line in f:
                    if line.strip().startswith("INSERT INTO `word`"):
                        cols_match = re.search(r'\((.*?)\)', line)
                        if cols_match:
                            cols_str = cols_match.group(1)
                            cols = [c.strip('` ') for c in cols_str.split(',')]
                            column_index_map = {col: idx for idx, col in enumerate(cols)}
                        continue
                        
                    if line.strip().startswith("(") and column_index_map:
                        vals = self._quick_parse_row(line.strip())
                        if len(vals) > column_index_map.get('html_id', 4):
                            html_val = vals[column_index_map['html_id']]
                            if isinstance(html_val, int) and html_val > max_html:
                                max_html = html_val
        except Exception:
            pass
        return max_html if max_html > 0 else 500000
