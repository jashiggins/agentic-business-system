def route_message(message, agents):
    target = message["to_agent_id"]
    agent = agents[target]
    return agent.handle(message)
