# Graph Framework — Nodes and Edges

## Overview

The graph framework defines the conversation flow as a directed graph of **nodes** (conversation states) and **edges** (transitions between states). It is a lightweight state-machine built on top of LangChain.

**Files:**
```
graph/
├── node.py             ← BaseNode abstract class
├── edge.py             ← BaseEdge abstract class
├── chain_based_node.py ← LLM-driven node
├── chain_based_edge.py ← LLM-driven edge
├── text_based_edge.py  ← Pattern-matching edge
└── static_text_node.py ← Fixed-response node
```

---

## Concepts

### Node
A **node** represents a conversation state. Each node:
- Has a `greeting_message()` — the message shown when the node is entered
- Has a list of outgoing **edges** — possible transitions
- Has a `no_edges_found()` handler — called when no edge matches

### Edge
An **edge** represents a transition condition. Each edge:
- Checks whether user input matches its condition
- If matched, returns an `EdgeOutput` with the target node
- Has retry logic for parsing failures

### Graph Traversal
```
User input arrives at current node
        ↓
Node tries each edge in order
        ↓
First edge that matches → returns EdgeOutput with next_node
        ↓
Pipeline moves to next_node
        ↓
next_node.greeting_message() shown to user
```

---

## BaseNode — `graph/node.py`

Abstract base class for all conversation nodes.

```python
class BaseNode(abc.ABC, Generic[NodeInput]):
    def __init__(self, edges: Optional[List[BaseEdge]] = None, final_state=False):
        self._edges = edges          # Outgoing edges
        self._node_input = None      # Input passed from previous edge
        self._final_state = final_state  # Whether this is a terminal state
```

### Methods

#### `execute(user_input) → Union[MessageOutput, EdgeOutput]`
Main execution method. Tries all edges; if none match, calls `no_edges_found()`.

```python
def execute(self, user_input):
    res = self.run_to_continue(user_input)
    if res is None or not res.should_continue:
        return self.no_edges_found(user_input)
    else:
        if res.next_node is not None:
            res.next_node.set_node_input(res.result)
    return res
```

#### `run_to_continue(user_input) → Optional[EdgeOutput]`
Iterates through edges until one returns `should_continue=True`.

```python
def run_to_continue(self, user_input):
    for edge in self._edges:
        res = edge.execute(user_input)
        if res is not None and res.should_continue:
            return res
    return res
```

#### Abstract methods (must be implemented by subclasses)
- `greeting_message() → Optional[MessageOutput]` — What to say when entering this node
- `no_edges_found(user_input) → Optional[MessageOutput]` — Fallback when no edge matches

---

## BaseEdge — `graph/edge.py`

Abstract base class for all conversation edges.

```python
class BaseEdge(abc.ABC, Generic[EdgeInput, ResultsType]):
    def __init__(self, model, max_retries=3, out_node=None):
        self._llm_model = model        # LLM for edge condition evaluation
        self._num_fails = 0            # Failure counter
        self._max_retries = max_retries  # Max retries before giving up
        self._out_node = out_node      # Target node if this edge matches
```

### Methods

#### `execute(user_input) → EdgeOutput`
Attempts to parse/evaluate the edge condition. Returns `EdgeOutput`.

```python
def execute(self, user_input):
    try:
        self._num_fails = 0
        return self._get_edge_output(
            should_continue=True,
            result=self._parse(user_input)
        )
    except OutputParserException as e:
        self._num_fails += 1
        if self._num_fails >= self._max_retries:
            # Give up and continue anyway
            return self._get_edge_output(should_continue=True, result=...)
        return self._get_edge_output(should_continue=False, result=...)
```

#### Abstract methods (must be implemented by subclasses)
- `_parse(model_input) → ResultsType` — Extract result from user input
- `check(model_output) → bool` — Validate parsed output
- `_get_message_output(msg_input) → Optional[List[MessageOutput]]` — Convert result to messages

---

## Data Models — `data/graph.py`

### MessageOutput
A single message to be displayed to the user.

```python
@dataclasses.dataclass
class MessageOutput:
    message: str   # Text content
    role: Role     # Role.USER, Role.SYSTEM, or Role.ASSISTANT
```

### EdgeOutput
Returned by every edge execution.

```python
@dataclasses.dataclass
class EdgeOutput:
    should_continue: bool                   # True = this edge matched
    result: Union[BaseModel, str]           # Parsed result (passed to next node)
    message_output: Optional[List[MessageOutput]]  # Messages to show
    num_fails: int                          # How many times edge failed
    next_node: "BaseNode"                   # Where to go next
```

---

## Concrete Implementations

### `graph/static_text_node.py` — StaticTextNode
A node that always returns a fixed text response regardless of input. Used for simple states like error messages or fallback responses.

```python
class StaticTextNode(BaseNode):
    def __init__(self, text: str, ...):
        self._text = text

    def greeting_message(self):
        return MessageOutput(message=self._text, role=Role.ASSISTANT)

    def no_edges_found(self, user_input):
        return MessageOutput(message=self._text, role=Role.ASSISTANT)
```

### `graph/chain_based_node.py` — ChainBasedNode
A node powered by an LLM chain. Generates dynamic responses using an LLM prompt chain.

```python
class ChainBasedNode(BaseNode):
    def __init__(self, chain, ...):
        self._chain = chain    # LangChain chain for response generation

    def no_edges_found(self, user_input):
        return self._chain.run(user_input)  # Generate dynamic response
```

### `graph/chain_based_edge.py` — ChainBasedEdge
An edge that uses an LLM to decide whether it matches, parsing structured output.

### `graph/text_based_edge.py` — TextBasedEdge
An edge that uses pattern matching (regex/keyword) rather than an LLM to decide if it matches. Faster and more deterministic than chain-based edges.

---

## Current Usage — GreetingNode

In the current application, only the `GreetingNode` from `agents/support.py` is active. It:
- Has **no edges** (empty list)
- Shows a welcome message as `greeting_message()`
- All actual queries bypass the graph and go directly to `HelpCenterAgent._run_query()`

```python
# In customer_support.py
def _get_pipeline(self) -> BaseNode:
    self._start_node = GreetingNode(edges=[])
    return self._start_node
```

The graph framework is designed to support multi-turn, multi-state conversations (e.g. booking flows, escalation paths) but is currently used in its simplest form — a single greeting state with direct RAG query handling.

---

## Extending the Graph

To add a new conversation flow (e.g. "Flight Booking"):

```python
# 1. Create a new node
class BookingNode(BaseNode):
    def greeting_message(self):
        return MessageOutput("Let's book your flight. Which route?", Role.ASSISTANT)

    def no_edges_found(self, user_input):
        return MessageOutput("I couldn't process that. Please try again.", Role.ASSISTANT)

# 2. Create an edge to route to it
class BookingEdge(TextBasedEdge):
    KEYWORDS = ["book", "reserve", "flight booking"]

    def check(self, model_output):
        return any(kw in model_output.lower() for kw in self.KEYWORDS)

# 3. Connect from GreetingNode
greeting = GreetingNode(edges=[BookingEdge(out_node=BookingNode())])
```
