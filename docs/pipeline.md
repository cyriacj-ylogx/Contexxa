# CustomerSupportPipeline — customer_support.py

## Overview

`CustomerSupportPipeline` is the main conversation orchestrator. It manages:
- Conversation state (current graph node)
- Conversation memory (chat history)
- Routing between the greeting flow and the RAG query engine

**File:** `Modular_Code/customer_support.py`

---

## Class: CustomerSupportPipeline

### Initialisation

```python
def __init__(self):
    self._llm_model   = AzureChatOpenAI(...)       # Azure OpenAI LLM
    self._memory      = ConversationBufferMemory()  # Chat history buffer
    self._current_node = None                       # Active graph node
    self._hc_agent    = HelpCenterAgent()           # RAG engine
```

**What happens on init:**
1. Connects to Azure OpenAI using credentials from `.env`
2. Creates a `ConversationBufferMemory` to store the chat history
3. Sets `_current_node` to None (pipeline not started yet)
4. Instantiates `HelpCenterAgent` which:
   - Loads or builds the ChromaDB vector index
   - Loads the embedding model
   - Loads the cross-encoder re-ranker

---

## Methods

### `_get_pipeline() → BaseNode`
Returns the starting node of the conversation graph — always `GreetingNode`.

```python
def _get_pipeline(self) -> BaseNode:
    self._start_node = GreetingNode(edges=[])
    return self._start_node
```

### `_set_current_node(node) → MessageOutput`
Sets the active node and returns its greeting message.

```python
def _set_current_node(self, node: BaseNode) -> MessageOutput:
    self._current_node = node
    return node.greeting_message()
```

### `run(user_input) → Tuple[List[MessageOutput], bool, Optional[dict]]`
Main execution method. Called for every user interaction.

**Returns:** `(messages, is_finished, response_dict)`

---

## Execution Flow

```
pipeline.run("") ← First call (empty string)
        ↓
_current_node is None?
        ↓ YES
Set current node → GreetingNode
Return greeting message
────────────────────────────────
pipeline.run("What is baggage allowance?") ← Subsequent calls
        ↓
_current_node exists
        ↓
user_input is not empty?
        ↓ YES
Call HelpCenterAgent._run_query(user_input)
        ↓
Get answer + sources
        ↓
Save to conversation memory
        ↓
Return [MessageOutput], True, response
```

---

## Conversation Memory

Uses LangChain's `ConversationBufferMemory`:
- Stores every user input and assistant output
- Memory key: `"chat_history"`
- Returns messages as LangChain message objects

```python
self._memory.save_context(
    {"input": user_input},
    {"output": answer}
)
```

> Note: Memory is currently used for storage but not injected into RAG queries. Each query is answered independently from documents.

---

## Return Values

| Field | Type | Description |
|---|---|---|
| `messages` | `List[MessageOutput]` | List of bot messages to display |
| `is_finished` | `bool` | Always `True` after first greeting |
| `response` | `Optional[dict]` | Dict with `answer` and `sources` from RAG |

**Response dict structure:**
```python
{
    "answer": "The baggage allowance is...",
    "sources": [
        {
            "content": "15kg per person...",
            "metadata": {"source": "Baggage Allowance.docx"},
            "score": 0.97
        }
    ]
}
```

---

## Fallback Handling

If the RAG engine returns an empty answer:
```python
if not answer.strip():
    answer = "I'm sorry, I don't have specific information about that. 
              Please check with IndiGo directly or visit their official website."
```
