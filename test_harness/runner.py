# Location: /test_harness/runner.py
# Purpose: Simple test harness runner to execute predefined scenarios.
# Usage: python runner.py test_case_1

import sys
import json
import os
from mock_agents import MockBroker, MockAgentRegistry

TEST_DIR = os.path.dirname(__file__)
CASES_DIR = os.path.join(TEST_DIR, "cases")

def load_case(name):
    path = os.path.join(CASES_DIR, f"{name}.json")
    with open(path) as f:
        return json.load(f)

def run_case(name):
    case = load_case(name)
    broker = MockBroker()
    registry = MockAgentRegistry(broker)
    # Register mock agents
    registry.register_default_agents()
    print(f"Running test case: {name}")
    for step in case["steps"]:
        broker.publish(step["message"])
    # Wait for processing (synchronous in mock)
    results = broker.get_results()
    print("Results:", json.dumps(results, indent=2))

if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python runner.py test_case_1")
        sys.exit(1)
    run_case(sys.argv[1])
