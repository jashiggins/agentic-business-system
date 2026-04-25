from router import route_message
from storage import save_log
from agents import load_agents

agents = load_agents()

def handle_message(message):
    routed = route_message(message, agents)
    save_log(routed)
    return routed
