import os
import sys
import re
import argparse
import time

# Ensure parent directory is in path
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PARENT_DIR = os.path.dirname(SCRIPT_DIR)
if PARENT_DIR not in sys.path:
    sys.path.append(PARENT_DIR)

try:
    from neo4j import GraphDatabase
except ImportError:
    print("❌ Error: The 'neo4j' Python package is not installed. Run 'pip install neo4j' to run this script.")
    sys.exit(1)

def parse_sql_values_row(val_str):
    """
    Parses a single row of values from an INSERT statement, e.g.:
    (548920, 'iз', 'iз', '...', 338274, ...)
    """
    vals = []
    i = 0
    val_str = val_str.strip()
    
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
        while i < n and (val_str[i].isspace() or val_str[i] == ','):
            i += 1
        if i >= n:
            break
        
        if val_str[i] == "'":
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

class Neo4jSync:
    def __init__(self, uri, user, password):
        self.driver = GraphDatabase.driver(uri, auth=(user, password))

    def close(self):
        self.driver.close()

    def setup_schema(self):
        """
        Creates constraints and indices for optimal performance.
        """
        with self.driver.session() as session:
            print("Creating Neo4j constraints and indices...")
            # Constraint for unique ID
            session.run("CREATE CONSTRAINT FOR (w:Word) REQUIRE w.id IS UNIQUE")
            # Indices on frequent lookup keys
            session.run("CREATE INDEX FOR (w:Word) REQUIRE w.word")
            session.run("CREATE INDEX FOR (w:Word) REQUIRE w.main_form_code")
            session.run("CREATE INDEX FOR (w:Word) REQUIRE w.is_main_form")

    def sync_sql_to_neo4j(self, sql_path, limit=None):
        """
        Parses SQL file and streams nodes and relationships in batches to Neo4j.
        """
        if not os.path.exists(sql_path):
            print(f"❌ SQL file not found: {sql_path}")
            return False

        start_time = time.time()
        print(f"Parsing SQL file for Neo4j: {sql_path}")
        
        column_index_map = {}
        nodes_batch = []
        
        # Batch sizes for uploads
        BATCH_SIZE = 1000
        total_synced = 0
        
        # 1. Parse SQL rows and upload nodes
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
                    try:
                        vals = parse_sql_values_row(line.strip())
                        if len(vals) < len(column_index_map):
                            continue
                        
                        # Extract necessary properties
                        row_id = int(vals[column_index_map['id']])
                        word = vals[column_index_map['word']]
                        part = vals[column_index_map['part_of_language']]
                        
                        is_main = int(vals[column_index_map['is_main_form']]) if column_index_map.get('is_main_form') is not None else 1
                        main_code = vals[column_index_map['main_form_code']] if column_index_map.get('main_form_code') is not None else ""
                        
                        # Extra properties
                        creature = vals[column_index_map.get('creature')] if 'creature' in column_index_map else "-"
                        genus = vals[column_index_map.get('genus')] if 'genus' in column_index_map else "-"
                        number = vals[column_index_map.get('number')] if 'number' in column_index_map else "-"
                        
                        # Levels and parents (might be added by agents)
                        level = vals[column_index_map['abstraction_level']] if 'abstraction_level' in column_index_map and vals[column_index_map['abstraction_level']] is not None else None
                        parent_id = vals[column_index_map['parent_id']] if 'parent_id' in column_index_map and vals[column_index_map['parent_id']] is not None else None
                        
                        node_data = {
                            "id": row_id,
                            "word": word,
                            "part_of_language": part,
                            "is_main_form": is_main,
                            "main_form_code": main_code,
                            "creature": creature,
                            "genus": genus,
                            "number": number,
                            "abstraction_level": level,
                            "parent_id": parent_id
                        }
                        
                        nodes_batch.append(node_data)
                        
                        if len(nodes_batch) >= BATCH_SIZE:
                            self._upload_nodes_batch(nodes_batch)
                            total_synced += len(nodes_batch)
                            nodes_batch = []
                            print(f"Synced {total_synced:,} nodes to Neo4j...")
                            
                        if limit and total_synced >= limit:
                            break
                    except Exception:
                        continue
                        
        if nodes_batch:
            self._upload_nodes_batch(nodes_batch)
            total_synced += len(nodes_batch)
            
        print(f"Finished node ingestion. Total synced: {total_synced:,} nodes.")

        # 2. Re-establish relationships (CHILD_OF and INFLECTION_OF) in batches
        print("Rebuilding graph relationships...")
        self._build_relationships(sql_path, limit)
        
        duration = time.time() - start_time
        print(f"✅ Sync complete in {duration:.2f} seconds.")
        return True

    def _upload_nodes_batch(self, batch):
        """
        Cypher batch merge query.
        """
        cypher = """
        UNWIND $batch AS row
        MERGE (w:Word {id: toInteger(row.id)})
        SET w.word = row.word,
            w.part_of_language = row.part_of_language,
            w.is_main_form = toInteger(row.is_main_form),
            w.main_form_code = row.main_form_code,
            w.creature = row.creature,
            w.genus = row.genus,
            w.number = row.number,
            w.abstraction_level = row.abstraction_level,
            w.parent_id = row.parent_id
        """
        with self.driver.session() as session:
            session.run(cypher, batch=batch)

    def _build_relationships(self, sql_path, limit=None):
        """
        Iterates over SQL file again to build CHILD_OF and INFLECTION_OF edges in batches.
        """
        column_index_map = {}
        rel_batch = []
        inf_batch = []
        BATCH_SIZE = 1000
        
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
                    try:
                        vals = parse_sql_values_row(line.strip())
                        if len(vals) < len(column_index_map):
                            continue
                        
                        row_id = int(vals[column_index_map['id']])
                        is_main = int(vals[column_index_map['is_main_form']]) if column_index_map.get('is_main_form') is not None else 1
                        main_code = vals[column_index_map['main_form_code']] if column_index_map.get('main_form_code') is not None else ""
                        parent_id = vals[column_index_map['parent_id']] if 'parent_id' in column_index_map and vals[column_index_map['parent_id']] is not None else None
                        
                        # 1. Child relationships (parent_id)
                        if parent_id is not None:
                            rel_batch.append({"child_id": row_id, "parent_id": int(parent_id)})
                            if len(rel_batch) >= BATCH_SIZE:
                                self._upload_child_relations(rel_batch)
                                rel_batch = []
                                
                        # 2. Inflection relationships
                        if is_main == 0 and main_code:
                            inf_batch.append({"inf_id": row_id, "main_code": main_code})
                            if len(inf_batch) >= BATCH_SIZE:
                                self._upload_inflection_relations(inf_batch)
                                inf_batch = []
                                
                    except Exception:
                        continue
                        
        if rel_batch:
            self._upload_child_relations(rel_batch)
        if inf_batch:
            self._upload_inflection_relations(inf_batch)

    def _upload_child_relations(self, batch):
        cypher = """
        UNWIND $batch AS row
        MATCH (c:Word {id: toInteger(row.child_id)})
        MATCH (p:Word {id: toInteger(row.parent_id)})
        MERGE (c)-[:CHILD_OF]->(p)
        """
        with self.driver.session() as session:
            session.run(cypher, batch=batch)

    def _upload_inflection_relations(self, batch):
        cypher = """
        UNWIND $batch AS row
        MATCH (inf:Word {id: toInteger(row.inf_id)})
        MATCH (lemma:Word {main_form_code: row.main_code, is_main_form: 1})
        MERGE (inf)-[:INFLECTION_OF]->(lemma)
        """
        with self.driver.session() as session:
            session.run(cypher, batch=batch)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Synchronize SQL dump into Neo4j graph database.")
    parser.add_argument("--input", default="base_of_word/Word.v.10.level.relationship.sql", help="Path to input SQL file")
    parser.add_argument("--limit", type=int, help="Limit number of rows synced (useful for testing)")
    args = parser.parse_args()

    # Load env vars
    from dotenv import load_dotenv
    load_dotenv()
    load_dotenv(dotenv_path='.env.local', override=True)

    uri = os.getenv("NEO4J_URI", "bolt://localhost:7687")
    user = os.getenv("NEO4J_USER", "neo4j")
    password = os.getenv("NEO4J_PASSWORD", "password")

    print(f"Connecting to Neo4j at {uri}...")
    sync = None
    try:
        sync = Neo4jSync(uri, user, password)
        sync.setup_schema()
        sync.sync_sql_to_neo4j(args.input, args.limit)
    except Exception as e:
        print(f"❌ Error during sync: {e}")
        sys.exit(1)
    finally:
        if sync:
            sync.close()
