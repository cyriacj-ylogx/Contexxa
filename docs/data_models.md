# Data Models

## Overview

Data classes and schemas used across the application for message passing, conversation history, and graph traversal.

**Files:**
```
data/
├── chat.py    ← Role enum, MessageHistory, ModelInput
└── graph.py   ← MessageOutput, EdgeOutput
```

---

## data/chat.py

### Role (Enum)

Defines the three speaker roles in a conversation.

```python
class Role(str, Enum):
    USER      = "user"       # Human speaker
    SYSTEM    = "system"     # System/instructions
    ASSISTANT = "assistant"  # Bot/AI speaker
```

Inherits from `str` so it serialises cleanly to JSON and LangChain message formats.

---

### ModelInput

Separates the current user input from the conversation history, for passing to LLM chains.

```python
@dataclasses.dataclass
class ModelInput:
    input:   str   # The latest user message only
    history: str   # All previous messages concatenated
```

---

### MessageHistory

Manages a list of conversation messages with helper methods.

```python
@dataclasses.dataclass
class MessageHistory:
    messages: List[dict]   # List of {"role": str, "content": str} dicts
```

#### Methods

| Method | Description |
|---|---|
| `add_user_message(content)` | Append a user message |
| `add_assistant_message(content)` | Append an assistant message |
| `add_system_message(content)` | Append a system message |
| `add_message(content, role)` | Append message with explicit role |
| `role_based_history(role)` | Filter messages by role |
| `model_input() → ModelInput` | Split into `input` (last user msg) + `history` (all prior) |
| `__str__()` | Format full history as `"\nrole: content"` string |

#### `model_input()` — How it works

```python
def model_input(self) -> ModelInput:
    # history = everything except last message
    history = "\n".join(f"{m['role']}: {m['content']}" for m in messages[:-1])

    # input = last user message only
    user_messages = self.role_based_history(role=Role.USER)
    last_msg = user_messages[-1]
    user_input = f"\n{last_msg['role']}: {last_msg['content']}"

    return ModelInput(input=user_input, history=history)
```

**Why separate input and history?**
LLM chains need:
- `history` for context about the conversation so far
- `input` for the current question to answer

---

## data/graph.py

### MessageOutput

A single message ready to be sent to the user.

```python
@dataclasses.dataclass
class MessageOutput:
    message: str   # Text content to display
    role: Role     # Who is speaking
```

Used everywhere messages are passed through the pipeline — from nodes, edges, and fallback handlers.

---

### EdgeOutput

The result returned by any edge execution. Contains everything the pipeline needs to decide what to do next.

```python
@dataclasses.dataclass
class EdgeOutput:
    should_continue: bool                        # True → edge matched, continue to next_node
    result: Union[BaseModel, str]                # Parsed output from the edge
    message_output: Optional[List[MessageOutput]]  # Messages to show user (if any)
    num_fails: int                               # How many times this edge failed
    next_node: "BaseNode"                        # Target node to transition to
```

#### Field meanings

| Field | Type | Description |
|---|---|---|
| `should_continue` | `bool` | If `True`, pipeline transitions to `next_node`. If `False`, edge did not match — try next edge. |
| `result` | `Union[BaseModel, str]` | Structured or raw parsed output from the edge logic |
| `message_output` | `Optional[List[MessageOutput]]` | Additional messages to display (e.g. intermediate steps) |
| `num_fails` | `int` | Tracks retry count. Resets to 0 on success. Used to decide when to give up. |
| `next_node` | `BaseNode` | The node to transition to if `should_continue=True` |

---

## agents/helpers.py

Utility functions for memory management and message formatting used by the pipeline.

```python
# Converts LangChain memory messages to MessageHistory format
def get_message_history(memory) -> MessageHistory:
    messages = memory.chat_memory.messages
    history = MessageHistory(messages=[])
    for msg in messages:
        if isinstance(msg, HumanMessage):
            history.add_user_message(msg.content)
        elif isinstance(msg, AIMessage):
            history.add_assistant_message(msg.content)
    return history
```

---

## Type Flow Through the Application

```
User question (str)
        ↓ customer_support.py
pipeline.run(user_input)
        ↓
HelpCenterAgent._run_query(user_input)
        ↓ returns dict
{
    "answer": str,
    "sources": List[dict]
}
        ↓ api.py
ChatResponse(answer=str, sources=List[Source])
        ↓ JSON
{
    "answer": "...",
    "sources": [{"content": ..., "source": ..., "score": ...}]
}
```
