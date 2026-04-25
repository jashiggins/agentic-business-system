# Location: /test_harness/mock_agents.py
# Purpose: Minimal mock broker and agent registry for test harness.
import json
from collections import defaultdict

class MockBroker:
    def __init__(self):
        self.queues = []
        self.results = []

    def publish(self, message):
        # In real system, message would be persisted and routed.
        self.queues.append(message)
        self.process(message)

    def process(self, message):
        # Very simple synchronous processing for tests.
        intent = message.get("intent")
        if intent == "CREATE_LEAD":
            self.results.append({"event":"lead_created","payload":message["payload"]})
        elif intent == "SEND_EMAIL":
            self.results.append({"event":"email_sent","payload":message["payload"]})
        elif intent == "RECORD_TRANSACTION":
            self.results.append({"event":"transaction_recorded","payload":message["payload"]})
        elif intent == "SIMULATE_PHISHING":
            self.results.append({"event":"phishing_quarantined","payload":message["payload"]})
        else:
            self.results.append({"event":"processed","intent":intent,"payload":message.get("payload")})

    def get_results(self):
        return self.results

class MockAgentRegistry:
    def __init__(self, broker):
        self.broker = broker
        self.agents = {}

    def register_default_agents(self):
        # Register minimal set for tests
        self.agents["agent_marketing"] = {"id":"agent_marketing"}
        self.agents["agent_finance"] = {"id":"agent_finance"}
        self.agents["agent_security"] = {"id":"agent_security"}
