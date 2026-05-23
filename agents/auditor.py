import os
import sys
import re

# Add parent directory to path
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PARENT_DIR = os.path.dirname(SCRIPT_DIR)
if PARENT_DIR not in sys.path:
    sys.path.append(PARENT_DIR)

from agents.base import BaseAgent

# Try importing neo4j
try:
    import neo4j
    from neo4j import GraphDatabase
except ImportError:
    neo4j = None

class Auditor(BaseAgent):
    def __init__(self):
        super().__init__(name="Auditor")
        self.neo4j_uri = os.getenv("NEO4J_URI", "bolt://localhost:7687")
        self.neo4j_user = os.getenv("NEO4J_USER", "neo4j")
        self.neo4j_password = os.getenv("NEO4J_PASSWORD", "password")

    async def audit_all(self):
        """
        Runs all audits: SQL checks and Neo4j graph integrity checks.
        Returns (success, error_message).
        """
        self.log("Starting comprehensive data audit...")
        
        errors = []
        warnings = []
        
        # 1. SQL File Checks
        sql_path = os.path.join(PARENT_DIR, "base_of_word", "Word.v.10.level.relationship.sql")
        if os.path.exists(sql_path):
            self.log(f"Auditing SQL dump: {sql_path}")
            sql_ok, sql_err = self._check_sql_syntax(sql_path)
            if not sql_ok:
                errors.append(f"SQL Integrity Error: {sql_err}")
            else:
                self.log("✅ SQL syntax check passed.")
        else:
            warnings.append("SQL relationship file does not exist yet; skipping SQL checks.")

        # 2. Neo4j Graph Database Checks
        if neo4j is None:
            warnings.append("Python 'neo4j' driver is not installed. Skipping Neo4j validation. Run 'pip install neo4j' to enable.")
        else:
            self.log(f"Connecting to Neo4j at {self.neo4j_uri}...")
            neo4j_ok, neo4j_errors = self._audit_neo4j_graph()
            if not neo4j_ok:
                errors.extend(neo4j_errors)
            else:
                self.log("✅ Neo4j graph integrity checks passed.")

        # Final reporting
        if warnings:
            self.log(f"⚠️ Warnings during audit:\n- " + "\n- ".join(warnings))
            
        if errors:
            err_summary = "; ".join(errors)
            self.log(f"❌ Audit failed with {len(errors)} errors: {err_summary}")
            return False, err_summary
        
        self.log("🎉 Audit completed successfully. No critical errors found.")
        return True, ""

    def _check_sql_syntax(self, file_path):
        """
        Quick check of SQL file to verify the column declarations and base syntax.
        """
        try:
            has_abstraction = False
            has_parent = False
            inside_create_table = False
            
            with open(file_path, "r", encoding="utf-8") as f:
                # Read first 100 lines for table structure
                for i in range(150):
                    line = f.readline()
                    if not line:
                        break
                    
                    if "CREATE TABLE" in line and "`word`" in line:
                        inside_create_table = True
                    
                    if inside_create_table:
                        if "`abstraction_level`" in line:
                            has_abstraction = True
                        if "`parent_id`" in line:
                            has_parent = True
                        if line.strip().startswith(")") or "ENGINE=" in line:
                            inside_create_table = False
            
            if not has_abstraction:
                return False, "Column 'abstraction_level' is missing from `word` table CREATE block."
            if not has_parent:
                return False, "Column 'parent_id' is missing from `word` table CREATE block."
                
            return True, ""
        except Exception as e:
            return False, f"Exception parsing SQL file: {e}"

    def _audit_neo4j_graph(self):
        """
        Connects to Neo4j and runs validation Cypher queries.
        """
        errors = []
        driver = None
        try:
            driver = GraphDatabase.driver(self.neo4j_uri, auth=(self.neo4j_user, self.neo4j_password))
            # Test connectivity
            driver.verify_connectivity()
            
            with driver.session() as session:
                # Check 1: Cycle detection
                cycle_query = "MATCH (w:Word)-[:CHILD_OF*]->(w) RETURN DISTINCT w.word LIMIT 20"
                result = session.run(cycle_query)
                cycles = [record["w.word"] for record in result]
                if cycles:
                    errors.append(f"Cycles detected in hierarchy for words: {', '.join(cycles)}")

                # Check 2: Orphans check (level 1-9 should have parents)
                orphan_query = """
                MATCH (w:Word) 
                WHERE w.is_main_form = 1 
                  AND toInteger(w.abstraction_level) < 10 
                  AND NOT (w)-[:CHILD_OF]->() 
                RETURN w.word LIMIT 20
                """
                result = session.run(orphan_query)
                orphans = [record["w.word"] for record in result]
                if orphans:
                    # We report orphans as warnings unless they exceed a threshold, 
                    # but for this audit we'll log it as a structural warning or error
                    self.log(f"⚠️ Found {len(orphans)} orphan main lemmas (level < 10 with no parent): {', '.join(orphans)}")

                # Check 3: Level hierarchy violation (e.g. Level 7 child of Level 5)
                violation_query = """
                MATCH (w1:Word)-[:CHILD_OF]->(w2:Word) 
                WHERE toInteger(w1.abstraction_level) > toInteger(w2.abstraction_level) 
                RETURN w1.word + ' (' + w1.abstraction_level + ') -> ' + w2.word + ' (' + w2.abstraction_level + ')' AS violation LIMIT 20
                """
                result = session.run(violation_query)
                violations = [record["violation"] for record in result]
                if violations:
                    errors.append(f"Hierarchy level violations (child level > parent level): {', '.join(violations)}")

        except Exception as e:
            # Connectivity or syntax errors in Cypher
            errors.append(f"Neo4j Connection/Query Error: {e}")
        finally:
            if driver:
                driver.close()

        if errors:
            return False, errors
        return True, []
