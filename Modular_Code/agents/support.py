import random
from typing import Optional

from data.chat import Role
from data.graph import MessageOutput
from graph.node import BaseNode

class GreetingNode(BaseNode[str]):
    STATIC_PROMPT = [
        "Hi, I'm your Airline Support Agent. How can I assist you today?"
    ]
    RETRY_PROMPT = [
        "I'm sorry, I didn't understand your question. Could you please rephrase it?"
    ]

    def greeting_message(self) -> Optional[MessageOutput]:
        prompt = random.choice(self.STATIC_PROMPT)
        return MessageOutput(prompt, role=Role.ASSISTANT)

    def no_edges_found(self, user_input: str) -> Optional[MessageOutput]:
        prompt = random.choice(self.RETRY_PROMPT)
        return MessageOutput(prompt, role=Role.ASSISTANT)
