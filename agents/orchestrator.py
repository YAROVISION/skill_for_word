import os
import sys
import json
import time
import asyncio
from agents.base import BaseAgent

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PARENT_DIR = os.path.dirname(SCRIPT_DIR)
SCRATCH_DIR = os.path.join(PARENT_DIR, "scratch")
STATE_PATH = os.path.join(SCRATCH_DIR, "agent_state.json")

os.makedirs(SCRATCH_DIR, exist_ok=True)

class Orchestrator(BaseAgent):
    def __init__(self):
        super().__init__(name="Orchestrator")
        self.state = self.load_state()

    def load_state(self):
        """
        Loads the agent state from the JSON state file.
        """
        if os.path.exists(STATE_PATH):
            try:
                with open(STATE_PATH, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception as e:
                self.log(f"Error loading state: {e}. Resetting state.")
        
        # Default state structure
        return {
            "session_id": "",
            "status": "idle", # idle, running, halted, completed, error
            "error_msg": "",
            "current_step_id": None,
            "plan": []
        }

    def save_state(self):
        """
        Saves the agent state to the JSON state file.
        """
        try:
            with open(STATE_PATH, "w", encoding="utf-8") as f:
                json.dump(self.state, f, ensure_ascii=False, indent=2)
        except Exception as e:
            self.log(f"Error saving state: {e}")

    def update_status(self, status, error_msg=""):
        """
        Updates the global execution status.
        """
        self.state["status"] = status
        self.state["error_msg"] = error_msg
        self.save_state()
        self.log(f"Status updated to: {status} (Error: '{error_msg}')")

    async def execute_step(self, step):
        """
        Executes a single step in the plan.
        """
        step_id = step["id"]
        task = step["task"]
        args = step.get("args", {})
        
        self.state["current_step_id"] = step_id
        step["status"] = "running"
        step["started_at"] = time.time()
        self.save_state()
        
        self.log(f"🚀 Running step {step_id}: {task} with args {args}")
        
        success = False
        error_info = ""
        
        try:
            if task == "classify_words":
                success, error_info = await self._run_subprocess_script(
                    "classify_words.py",
                    [
                        "--input", args.get("input", "base_of_word/Word.v.10.sql"),
                        "--output", args.get("output", "base_of_word/Word.v.10.level.sql"),
                        "--api-type", args.get("api-type", "rotator"),
                        "--model", args.get("model", "groq"),
                        "--progress-file", os.path.join(SCRATCH_DIR, "classification_progress.json")
                    ] + (["--heuristics-only"] if args.get("heuristics-only") else [])
                      + (["--limit", str(args["limit"])] if args.get("limit") else [])
                )
            elif task == "build_relationships":
                success, error_info = await self._run_subprocess_script(
                    "word_relationship.py",
                    [
                        "--input", args.get("input", "base_of_word/Word.v.10.level.sql"),
                        "--output", args.get("output", "base_of_word/Word.v.10.level.relationship.sql"),
                        "--api-type", args.get("api-type", "rotator"),
                        "--model", args.get("model", "groq"),
                        "--progress-file", os.path.join(SCRATCH_DIR, "relationship_progress.json")
                    ] + (["--limit", str(args["limit"])] if args.get("limit") else [])
                )
            elif task == "generate_obsidian":
                success, error_info = await self._run_subprocess_script(
                    "generate_obsidian_db.py", []
                )
            elif task == "sync_neo4j":
                # We will implement neo4j_sync.py later
                success, error_info = await self._run_subprocess_script(
                    "agents/neo4j_sync.py",
                    ["--input", args.get("input", "base_of_word/Word.v.10.level.relationship.sql")]
                )
            elif task == "audit_integrity":
                # Auditor checks
                from agents.auditor import Auditor
                auditor = Auditor()
                success, error_info = await auditor.audit_all()
            else:
                success = False
                error_info = f"Unknown task: {task}"
                
        except Exception as e:
            success = False
            error_info = str(e)
            
        step["finished_at"] = time.time()
        if success:
            step["status"] = "completed"
            self.log(f"✅ Step {step_id} completed successfully.")
            self.save_state()
            return True
        else:
            step["status"] = "failed"
            step["error"] = error_info
            self.log(f"❌ Step {step_id} failed: {error_info}")
            
            # HALT: Ask for user intervention
            self.update_status("halted", f"Error on step {step_id} ({task}): {error_info}")
            return False

    async def _run_subprocess_script(self, script_name, args):
        """
        Helper method to run python script as a subprocess.
        """
        script_path = os.path.join(PARENT_DIR, script_name)
        cmd = [sys.executable, script_path] + args
        
        self.log(f"Running subprocess: {' '.join(cmd)}")
        try:
            process = await asyncio.create_subprocess_exec(
                *cmd,
                cwd=PARENT_DIR,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            
            stdout, stderr = await process.communicate()
            
            if process.returncode == 0:
                return True, ""
            else:
                err_msg = stderr.decode('utf-8', errors='ignore').strip() or stdout.decode('utf-8', errors='ignore').strip()
                return False, f"Process exited with code {process.returncode}. Error: {err_msg[:200]}"
        except Exception as e:
            return False, f"Exception starting script: {e}"

    async def start_pipeline(self, new_plan=None):
        """
        Starts or resumes the execution pipeline.
        """
        self.state = self.load_state()
        
        if new_plan:
            self.state["plan"] = new_plan
            self.state["session_id"] = f"session_{int(time.time())}"
            self.state["current_step_id"] = None
            self.update_status("running")
        elif self.state["status"] == "halted":
            self.update_status("running", "Resumed by user")
        elif self.state["status"] == "running":
            self.log("Pipeline is already running.")
            return
        else:
            self.log("No plan to run. Triggering Planner.")
            from agents.planner import Planner
            planner = Planner()
            plan = await planner.generate_plan()
            if plan:
                await self.start_pipeline(plan)
                return
            else:
                self.update_status("error", "Failed to generate plan.")
                return

        # Execution loop
        while self.state["status"] == "running":
            # Load fresh state (in case it was modified externally, e.g., stopped)
            self.state = self.load_state()
            if self.state["status"] != "running":
                break
                
            # Find next pending task
            next_step = None
            for step in self.state["plan"]:
                if step["status"] == "pending":
                    next_step = step
                    break
                    
            if not next_step:
                # All steps finished!
                self.update_status("completed")
                self.state["current_step_id"] = None
                self.save_state()
                self.log("🎉 Pipeline execution completed successfully!")
                break
                
            step_success = await self.execute_step(next_step)
            if not step_success:
                # Execution halted on failure
                break
            
            # Small yield to let event loop process other stuff
            await asyncio.sleep(0.5)

    def stop_pipeline(self):
        """
        Gracefully stops execution.
        """
        self.state = self.load_state()
        if self.state["status"] == "running":
            self.update_status("halted", "Stopped by user")
            self.log("🛑 Pipeline execution stopped by user request.")
        else:
            self.log("Pipeline is not running.")
