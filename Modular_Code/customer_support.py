import threading
from typing import Optional, List, Tuple

from langchain_openai import AzureChatOpenAI
import os

from agents.support import GreetingNode
from data.chat import Role
from data.graph import MessageOutput
from graph.node import BaseNode
from state_store import StateStore
from tools.pageindex_responder import HelpCenterAgent


class CustomerSupportPipeline:

    # Per-session history limit (session count/age pruning lives in StateStore)
    MAX_HISTORY_TURNS = 6      # last N (user, assistant) pairs kept per session

    CONDENSE_PROMPT = (
        "Rewrite the follow-up question as a single short standalone question.\n"
        "Rules:\n"
        "- Replace pronouns and references ('it', 'them', 'that', 'this fee') "
        "with the specific noun/topic they refer to from the conversation.\n"
        "- Do NOT add any facts, numbers, prices, or details from previous "
        "answers — only substitute the topic noun.\n"
        "- Keep it as close to the original wording as possible.\n"
        "- If the follow-up is already standalone, return it unchanged.\n"
        "- Return ONLY the rewritten question, nothing else.\n\n"
        "Example:\n"
        "History: User asked about lounge guest cost; assistant answered INR 1,500.\n"
        "Follow-up: And how many of them can I bring?\n"
        "Standalone: How many guests can I bring into the lounge?\n\n"
        "Conversation history:\n{history}\n\n"
        "Follow-up question: {question}\n\n"
        "Standalone question:"
    )

    def __init__(self):
        self._llm_model = AzureChatOpenAI(
            azure_deployment=os.environ["AZURE_DEPLOYMENT_NAME"],
            azure_endpoint=os.environ["AZURE_OPENAI_ENDPOINT"],
            api_key=os.environ["AZURE_OPENAI_API_KEY"],
            api_version=os.environ.get("AZURE_OPENAI_API_VERSION", "2024-02-15-preview"),
            temperature=0,
        )
        # Session histories live in SQLite so they survive restarts and are
        # shared across uvicorn workers.
        self._state = StateStore()
        self._current_node = None
        self._hc_agent = HelpCenterAgent()
        self._index_version = self._state.get_index_version()
        self._reload_lock = threading.Lock()

    def _get_pipeline(self) -> BaseNode:
        self._start_node = GreetingNode(edges=[])
        return self._start_node

    def _set_current_node(self, node: BaseNode) -> MessageOutput:
        self._current_node = node
        return node.greeting_message()

    # ── Session memory (SQLite-backed) ────────────────────────────────
    def _get_history(self, session_id: str) -> list:
        return self._state.get_history(session_id)

    def _save_turn(self, session_id: str, user_msg: str, assistant_msg: str):
        history = self._state.get_history(session_id)
        history.append((user_msg, assistant_msg))
        history = history[-self.MAX_HISTORY_TURNS:]
        self._state.save_history(session_id, history)

    # ── Index staleness (multi-worker) ────────────────────────────────
    def _ensure_fresh_index(self):
        """Reload the RAG agent if another process rebuilt the index."""
        current = self._state.get_index_version()
        if current == self._index_version:
            return
        # Don't reload while a rebuild is still writing the persist dir.
        if self._state.lock_is_held("rebuild"):
            return
        with self._reload_lock:
            if current != self._index_version:
                self._hc_agent = HelpCenterAgent()
                self._index_version = current

    # ── Question condensation ─────────────────────────────────────────
    def _condense_question(self, session_id: str, question: str) -> str:
        """Rewrite a follow-up question as standalone using chat history."""
        import time as _time

        self._last_condense = {"ran": False, "ms": 0}
        history = self._get_history(session_id)
        if not history:
            return question

        history_text = "\n".join(
            f"User: {u}\nAssistant: {a}" for u, a in history
        )
        prompt = self.CONDENSE_PROMPT.format(history=history_text, question=question)
        try:
            _t0 = _time.perf_counter()
            from langchain.messages import HumanMessage
            rewritten = self._llm_model.invoke([HumanMessage(content=prompt)]).content.strip()
            self._last_condense = {
                "ran": True,
                "ms": int((_time.perf_counter() - _t0) * 1000),
            }
            return rewritten if rewritten else question
        except Exception:
            # On any LLM failure, fall back to the raw question
            return question

    def run(
        self, user_input: Optional[str], session_id: str = "default"
    ) -> Tuple[List[MessageOutput], bool, Optional[dict]]:
        assistant_output: List[MessageOutput] = []

        if self._current_node is None:
            greeting = self._set_current_node(self._get_pipeline())
            return [greeting], self._current_node.is_node_final(), None

        if user_input:
            # Reload the RAG agent if another worker rebuilt the index.
            self._ensure_fresh_index()
            # Resolve pronouns/references using this session's history,
            # then retrieve with the standalone question.
            standalone = self._condense_question(session_id, user_input)
            response = self._hc_agent._run_query(standalone)
            answer = response["answer"]

            if not answer.strip():
                answer = (
                    "I'm sorry, I don't have specific information about that. "
                    "Please check with IndiGo directly or visit their official website."
                )

            self._save_turn(session_id, user_input, answer)
            response["standalone_question"] = standalone
            response["trace_condense"] = getattr(
                self, "_last_condense", {"ran": False, "ms": 0}
            )

            assistant_output.append(MessageOutput(message=answer, role=Role.ASSISTANT))
            return assistant_output, True, response

        return assistant_output, True, None


if __name__ == "__main__":

    def print_messages(res):
        if res is not None:
            for out in res:
                if isinstance(out, MessageOutput):
                    print(out.message)

    pipeline = CustomerSupportPipeline()
    res, is_over, _ = pipeline.run("")
    print_messages(res)

    while not is_over:
        query = input()
        res, is_over, _ = pipeline.run(query)
        print_messages(res)
