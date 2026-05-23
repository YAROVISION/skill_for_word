import os
import sys
import time
from agents.base import BaseAgent

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PARENT_DIR = os.path.dirname(SCRIPT_DIR)
BASE_OF_WORD = os.path.join(PARENT_DIR, "base_of_word")

class Planner(BaseAgent):
    def __init__(self):
        super().__init__(name="Planner")

    async def generate_plan(self, api_type="rotator", model_name="groq"):
        """
        Dynamically analyzes the files in the workspace and builds a task execution plan.
        """
        self.log("Analyzing workspace to generate plan...")
        
        # Define paths
        input_sql = os.path.join(BASE_OF_WORD, "Word.v.10.sql")
        level_sql = os.path.join(BASE_OF_WORD, "Word.v.10.level.sql")
        rel_sql = os.path.join(BASE_OF_WORD, "Word.v.10.level.relationship.sql")
        obsidian_dir = os.path.join(PARENT_DIR, "obsidian_words_db")

        # Basic validation
        if not os.path.exists(input_sql):
            self.log(f"⚠️ Warning: Original dump not found at {input_sql}. Assuming testing or custom files.")
            # If the base file doesn't exist, we can't do much, but let's assume we proceed with whatever exists.

        # Step 1: Classify words
        step1_status = "pending"
        if os.path.exists(level_sql):
            if os.path.exists(input_sql) and os.path.getmtime(level_sql) >= os.path.getmtime(input_sql):
                self.log("✅ Abstraction level SQL is up to date. Marking classify_words as completed.")
                step1_status = "completed"
            elif not os.path.exists(input_sql):
                self.log("✅ Abstraction level SQL exists. Marking classify_words as completed.")
                step1_status = "completed"

        # Step 2: Build relationships
        step2_status = "pending"
        if os.path.exists(rel_sql):
            if os.path.exists(level_sql) and os.path.getmtime(rel_sql) >= os.path.getmtime(level_sql):
                self.log("✅ Word relationships SQL is up to date. Marking build_relationships as completed.")
                step2_status = "completed"

        # Step 3: Generate Obsidian DB
        step3_status = "pending"
        if os.path.exists(obsidian_dir) and len(os.listdir(obsidian_dir)) > 0:
            # Check if rel_sql exists and is older than obsidian files
            if os.path.exists(rel_sql) and os.path.getmtime(obsidian_dir) >= os.path.getmtime(rel_sql):
                self.log("✅ Obsidian notes directory exists and is up to date. Marking generate_obsidian as completed.")
                step3_status = "completed"

        # Step 4: Neo4j Synchronization (run if anything changed, or defaults to pending for safety)
        step4_status = "pending"
        
        # Step 5: Audit (always runs at the end to check everything)
        step5_status = "pending"

        # Assemble plan
        plan = [
            {
                "id": 1,
                "task": "classify_words",
                "args": {
                    "input": "base_of_word/Word.v.10.sql",
                    "output": "base_of_word/Word.v.10.level.sql",
                    "api-type": api_type,
                    "model": model_name
                },
                "status": step1_status,
                "started_at": None,
                "finished_at": None
            },
            {
                "id": 2,
                "task": "build_relationships",
                "args": {
                    "input": "base_of_word/Word.v.10.level.sql",
                    "output": "base_of_word/Word.v.10.level.relationship.sql",
                    "api-type": api_type,
                    "model": model_name
                },
                "status": step2_status,
                "started_at": None,
                "finished_at": None
            },
            {
                "id": 3,
                "task": "generate_obsidian",
                "args": {},
                "status": step3_status,
                "started_at": None,
                "finished_at": None
            },
            {
                "id": 4,
                "task": "sync_neo4j",
                "args": {
                    "input": "base_of_word/Word.v.10.level.relationship.sql"
                },
                "status": step4_status,
                "started_at": None,
                "finished_at": None
            },
            {
                "id": 5,
                "task": "audit_integrity",
                "args": {},
                "status": step5_status,
                "started_at": None,
                "finished_at": None
            }
        ]

        self.log(f"Generated plan with {len(plan)} steps.")
        return plan
