from langchain.messages import BaseMessage, HumanMessage, AIMessage
import json

def serialize_message(message: BaseMessage) -> dict:
    return {
        "type": type(message).__name__,
        "content": message.content,
        "metadata": message.metadata
    }

def deserialize_message(data: dict) -> BaseMessage:
    message_type = data.get("type")
    content = data.get("content")
    metadata = data.get("metadata", {})

    if message_type == "HumanMessage":
        return HumanMessage(content=content, metadata=metadata)
    elif message_type == "AIMessage":
        return AIMessage(content=content, metadata=metadata)
    else:
        raise ValueError(f"Unsupported message type: {message_type}")

def save_memory_to_file(memory, file_path="memory.json"):
    memory_data = memory.load_memory_variables({})
    # Serialize messages in the memory
    if "chat_history" in memory_data:
        memory_data["chat_history"] = [serialize_message(msg) for msg in memory_data["chat_history"]]
    with open(file_path, "w") as f:
        json.dump(memory_data, f)

def load_memory_from_file(memory, file_path="memory.json"):
    try:
        with open(file_path, "r") as f:
            memory_data = json.load(f)
            # Deserialize messages and load them into memory
            if "chat_history" in memory_data:
                memory_data["chat_history"] = [deserialize_message(msg) for msg in memory_data["chat_history"]]
                for item in memory_data["chat_history"]:
                    memory.save_context({"input": item.content}, {"output": ""})
    except FileNotFoundError:
        pass
