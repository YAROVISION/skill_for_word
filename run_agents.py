import os
import sys
import asyncio
import argparse

# Ensure this directory is in the path
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if SCRIPT_DIR not in sys.path:
    sys.path.append(SCRIPT_DIR)

from agents.orchestrator import Orchestrator

async def main():
    parser = argparse.ArgumentParser(description="Run the Multi-Agent orchestrator pipeline.")
    parser.add_argument("--api-type", default="rotator", help="Preferred API type")
    parser.add_argument("--model", default="groq", help="Preferred model name")
    args = parser.parse_args()

    print("🤖 Booting Orchestrator...")
    orchestrator = Orchestrator()
    
    # Run the orchestrator start method
    # It will automatically generate a plan using Planner if none exists
    await orchestrator.start_pipeline()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n🛑 Pipeline interrupted by user.")
        sys.exit(0)
