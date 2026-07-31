import json

from openai import OpenAI

from .tool_registry import TOOLS
from .tool_executor import execute_tool

client = OpenAI(
    base_url="http://localhost:11434/v1",
    api_key="ollama"
)

MODEL = "llama3.2:3b"


def ask_gpt(message: str):

    system_prompt = f"""
You are an AI CRM Assistant.

Available tools:

{json.dumps(TOOLS, indent=2)}

Rules:

1. If the user wants to retrieve a customer, respond ONLY with:

{{
    "tool":"crm",
    "operation":"read_customer",
    "parameters": {{
        "customer_id":"CUSTOMER_ID"
    }}
}}

2. If the user wants to update a customer, respond ONLY with:

{{
    "tool":"crm",
    "operation":"write_customer",
    "parameters": {{
        "customer_id":"CUSTOMER_ID",
        "changes": {{
            "email":"new@email.com"
        }}
    }}
}}

3. If the user wants to delete a customer, respond ONLY with:

{{
    "tool":"crm",
    "operation":"delete_customer",
    "parameters": {{
        "customer_id":"CUSTOMER_ID"
    }}
}}

If a tool is required,
respond ONLY with JSON.

Otherwise answer normally.
"""

    response = client.chat.completions.create(
        model=MODEL,
        messages=[
            {
                "role": "system",
                "content": system_prompt
            },
            {
                "role": "user",
                "content": message
            }
        ]
    )

    reply = response.choices[0].message.content

    try:
        tool_call = json.loads(reply)

        if "tool" in tool_call:
            return execute_tool(
                tool_call["tool"],
                tool_call["operation"],
                tool_call["parameters"]
            )

    except Exception:
        pass

    return {
        "response": reply
    }