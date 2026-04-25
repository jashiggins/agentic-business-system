import json
import glob

def load_agents():
    agents = {}
    for file in glob.glob("agents/*.json"):
        with open(file) as f:
            data = json.load(f)
            agents[data["id"]] = Agent(data)
    return agents

class Agent:
    def __init__(self, config):
        self.config = config

    def handle(self, message):
        return {
            "status": "processed",
            "agent": self.config["id"],
            "message": message
        }
