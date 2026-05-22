import os
import re
import sys
import json
import time

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

def sanitize_filename(name):
    # Obsidian names can't contain: * " \ / < > : | ?
    return re.sub(r'[*"\\\/<>:|?]', '_', name)

def main():
    input_path = "/Users/kostantinkrivula/Desktop/sqlbase/skill_for_word/base_of_word/Word.v.10.level.relationship.sql"
    output_dir = "/Users/kostantinkrivula/Desktop/sqlbase/skill_for_word/obsidian_words_db"
    
    print(f"Reading input file: {input_path}")
    if not os.path.exists(input_path):
        print(f"Error: {input_path} not found.")
        sys.exit(1)
        
    start_time = time.time()
    
    # LEVEL FOLDERS
    LEVEL_FOLDERS = {
        10: "10_Абсолют_Буття",
        9: "09_Сутність_Концепт",
        8: "08_Матеріальність_Тіло",
        7: "07_Походження_Генезис",
        6: "06_Призначення_Роль",
        5: "05_Категорія_Кластер",
        1: "01_Одиниця_Індивід"
    }
    
    # 1. Parse SQL rows and gather database records
    print("Parsing SQL database rows...")
    column_index_map = {}
    
    # list of all lemmas
    lemmas_list = []
    # main_form_code -> lemma info
    lemmas_by_code = {}
    # id -> lemma info
    lemmas_by_id = {}
    # main_form_code -> list of inflection words (aliases)
    aliases_by_code = {}
    
    line_count = 0
    row_count = 0
    
    with open(input_path, "r", encoding="utf-8") as f:
        for line in f:
            line_count += 1
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
                    row_count += 1
                    
                    row_id = int(vals[column_index_map['id']])
                    word = vals[column_index_map['word']]
                    main_code = vals[column_index_map['main_form_code']]
                    is_main = int(vals[column_index_map['is_main_form']])
                    level = int(vals[column_index_map['abstraction_level']]) if vals[column_index_map['abstraction_level']] is not None else None
                    parent_id = int(vals[column_index_map['parent_id']]) if vals[column_index_map['parent_id']] is not None else None
                    
                    # Gather extra fields
                    extra_fields = {}
                    for col, idx in column_index_map.items():
                        if col not in ['id', 'word', 'word_binary', 'unique_code', 'html_id', 'main_form_code', 'is_main_form', 'abstraction_level', 'parent_id', 'created_at', 'updated_at']:
                            val = vals[idx]
                            if val is not None and val != '-':
                                extra_fields[col] = val
                                
                    if is_main == 1:
                        lemma_data = {
                            'id': row_id,
                            'word': word,
                            'main_form_code': main_code,
                            'level': level,
                            'parent_id': parent_id,
                            'metadata': extra_fields
                        }
                        lemmas_list.append(lemma_data)
                        lemmas_by_code[main_code] = lemma_data
                        lemmas_by_id[row_id] = lemma_data
                    else:
                        if main_code not in aliases_by_code:
                            aliases_by_code[main_code] = set()
                        aliases_by_code[main_code].add(word)
                except Exception as e:
                    # Ignore corrupted line parse errors
                    continue
                    
    print(f"Finished parsing. Total rows parsed: {row_count}. Total lemmas found: {len(lemmas_list)}.")
    
    # 2. Handle naming collisions (Case-insensitive collision check)
    print("Checking for naming collisions and preparing filenames...")
    spelling_groups = {} # lowercase word -> list of lemma records
    for lemma in lemmas_list:
        w_lower = lemma['word'].lower()
        if w_lower not in spelling_groups:
            spelling_groups[w_lower] = []
        spelling_groups[w_lower].append(lemma)
        
    id_to_filename = {} # row_id -> filename (without .md)
    id_to_folder = {}   # row_id -> folder name relative to vault
    
    for w_lower, group in spelling_groups.items():
        if len(group) == 1:
            lemma = group[0]
            sanitized = sanitize_filename(lemma['word'])
            id_to_filename[lemma['id']] = sanitized
        else:
            # Sort group by ID for deterministic collision names
            group.sort(key=lambda x: x['id'])
            # Track duplicates of exact spelling and part of speech
            pos_counts = {}
            for lemma in group:
                pos = lemma['metadata'].get('part_of_language', 'невідомо')
                pos_counts[pos] = pos_counts.get(pos, 0) + 1
                
            pos_seen = {}
            for lemma in group:
                pos = lemma['metadata'].get('part_of_language', 'невідомо')
                pos_seen[pos] = pos_seen.get(pos, 0) + 1
                
                # If there are duplicate POS for same spelling, include the database ID
                if pos_counts[pos] > 1:
                    suffix = f"{pos} - {lemma['id']}"
                else:
                    suffix = pos
                    
                filename_base = f"{lemma['word']} ({suffix})"
                sanitized = sanitize_filename(filename_base)
                id_to_filename[lemma['id']] = sanitized
                
    # Define folder path for each lemma
    for lemma in lemmas_list:
        lvl = lemma['level']
        folder_name = LEVEL_FOLDERS.get(lvl, f"Level_{lvl}" if lvl is not None else "Unclassified")
        id_to_folder[lemma['id']] = folder_name
        
    # Build list of children for each parent
    print("Building children map...")
    children_by_parent = {} # parent_id -> list of child lemma ids
    for lemma in lemmas_list:
        pid = lemma['parent_id']
        if pid is not None:
            if pid not in children_by_parent:
                children_by_parent[pid] = []
            children_by_parent[pid].append(lemma['id'])
            
    # Create level directories
    os.makedirs(output_dir, exist_ok=True)
    for folder_name in LEVEL_FOLDERS.values():
        os.makedirs(os.path.join(output_dir, folder_name), exist_ok=True)
    os.makedirs(os.path.join(output_dir, "Unclassified"), exist_ok=True)
    
    # 3. Generate markdown files
    print(f"Writing {len(lemmas_list)} markdown files into Obsidian database...")
    files_written = 0
    
    for lemma in lemmas_list:
        row_id = lemma['id']
        word = lemma['word']
        main_code = lemma['main_form_code']
        lvl = lemma['level']
        pid = lemma['parent_id']
        metadata = lemma['metadata']
        
        filename = id_to_filename[row_id] + ".md"
        folder = id_to_folder[row_id]
        filepath = os.path.join(output_dir, folder, filename)
        
        # Get parent details
        parent_link = None
        if pid is not None:
            if pid in id_to_filename:
                parent_name = id_to_filename[pid]
                parent_link = f"[[{parent_name}]]"
            else:
                # If parent ID isn't a lemma (should not happen based on our analysis)
                parent_link = f"ID {pid}"
                
        # Get children details
        children_links = []
        child_ids = children_by_parent.get(row_id, [])
        # Sort children by word name
        child_ids.sort(key=lambda x: lemmas_by_id[x]['word'] if x in lemmas_by_id else '')
        for cid in child_ids:
            if cid in id_to_filename:
                child_name = id_to_filename[cid]
                children_links.append(f"[[{child_name}]]")
                
        # Get aliases (inflections)
        inflections = sorted(list(aliases_by_code.get(main_code, [])))
        
        # Write YAML frontmatter
        word_esc = word.replace('&', '&amp;').replace('"', '\\"')
        yaml_lines = [
            "---",
            f"id: {row_id}",
            f"word: \"{word_esc}\"",
            f"abstraction_level: {lvl if lvl is not None else 'null'}",
        ]
        
        if parent_link:
            yaml_lines.append(f"parent: \"{parent_link}\"")
        else:
            yaml_lines.append("parent: null")
            
        # Write metadata
        for k, v in metadata.items():
            if isinstance(v, str):
                v_esc = v.replace('"', '\\"')
                yaml_lines.append(f"{k}: \"{v_esc}\"")
            else:
                yaml_lines.append(f"{k}: {v}")
                
        if inflections:
            # Escape strings for yaml array
            escaped_infs = []
            for inf in inflections:
                inf_esc = inf.replace('"', '\\"')
                escaped_infs.append(f'"{inf_esc}"')
            aliases_str = ", ".join(escaped_infs)
            yaml_lines.append(f"aliases: [{aliases_str}]")
            
        yaml_lines.append("---")
        
        # Write body
        body_lines = [
            f"# {word}",
            ""
        ]
        
        # Metadata block
        pos = metadata.get('part_of_language', '-')
        level_desc = LEVEL_FOLDERS.get(lvl, f"Рівень {lvl}") if lvl is not None else "Невідомий рівень"
        body_lines.append("## ℹ️ Загальна інформація")
        body_lines.append(f"- **Частина мови:** {pos}")
        body_lines.append(f"- **Рівень абстракції:** {lvl} ({level_desc})")
        
        # Parent link in body
        body_lines.append("")
        body_lines.append("## 🔗 Зв'язки")
        if parent_link:
            body_lines.append(f"- **Батьківське поняття (гіперонім):** {parent_link}")
        else:
            body_lines.append("- **Батьківське поняття (гіперонім):** немає (вершина ієрархії)")
            
        # Children list in body
        if children_links:
            body_lines.append("- **Дочірні поняття (гіпоніми):**")
            for cl in children_links:
                body_lines.append(f"  - {cl}")
        else:
            body_lines.append("- **Дочірні поняття (гіпоніми):** немає дочірніх понять")
            
        # Inflections block
        if inflections:
            body_lines.append("")
            body_lines.append("## 📝 Граматичні форми слова (аліаси)")
            for inf in inflections:
                body_lines.append(f"- {inf}")
                
        # Write to file
        try:
            with open(filepath, "w", encoding="utf-8") as out:
                out.write("\n".join(yaml_lines) + "\n\n" + "\n".join(body_lines) + "\n")
            files_written += 1
            if files_written % 5000 == 0:
                print(f"Written {files_written:,} notes...")
        except Exception as e:
            print(f"Error writing to {filepath}: {e}")
            
    duration = time.time() - start_time
    print(f"Done! Successfully generated {files_written:,} Obsidian notes in {duration:.2f} seconds.")
    print(f"Vault location: {output_dir}")

if __name__ == '__main__':
    main()
