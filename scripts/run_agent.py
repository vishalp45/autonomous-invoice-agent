"""Run the agent:  python scripts/run_agent.py "Enter the latest Acme invoice into the finance system" """
import sys
sys.path.insert(0, ".")
from agent.loop import run_agent

task = sys.argv[1] if len(sys.argv) > 1 else \
    "Find the latest invoice from Acme Corp and enter it into the finance system. Tell me when it is done."
print("TASK:", task)
print("\nFINAL:", run_agent(task))
