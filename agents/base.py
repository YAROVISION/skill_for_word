import os
import sys

# Ensure the parent directory is in the system path to import llm_rotator
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PARENT_DIR = os.path.dirname(SCRIPT_DIR)
if PARENT_DIR not in sys.path:
    sys.path.append(PARENT_DIR)

try:
    from llm_rotator import LLMRotator
except ImportError:
    LLMRotator = None

class BaseAgent:
    def __init__(self, name="BaseAgent"):
        self.name = name
        if LLMRotator is not None:
            self.rotator = LLMRotator()
        else:
            self.rotator = None
            print(f"⚠️ [Agent: {self.name}] LLMRotator could not be loaded. AI calls will fail.")

    def chat(self, prompt, system_prompt=None, response_format=None, preferred_provider=None):
        """
        Sends a query to the LLM rotator with an optional system prompt.
        """
        if not self.rotator:
            raise Exception("LLM Rotator is not initialized.")
        
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        return self.rotator.chat_completion(
            messages=messages,
            response_format=response_format,
            preferred_provider=preferred_provider
        )

    def log(self, message):
        print(f"🤖 [{self.name}]: {message}")
