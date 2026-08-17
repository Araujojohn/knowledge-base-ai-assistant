import os
from dotenv import load_dotenv
from prompts import openai_realtimeapi_prompt, openai_realtimeapi_tool_description , openai_realtimeapi_tool_name, openai_realtimeapi_tool_args_description
import httpx


load_dotenv()
client = httpx.AsyncClient()
openai_api_key = os.getenv("OPENAI_API_TOKEN") 

async def  create_openai_realtime_session() -> str: 
    "Calls OpenAi realtime api to initialize a session"

    
    url = "https://api.openai.com/v1/realtime/client_secrets"

    headers = {
        "Authorization": f"Bearer {openai_api_key}",
    }

    params = {
        "session": {
            "type": "realtime",
            "model": "gpt-realtime",
            "voice": "cedar",
            "instructions": openai_realtimeapi_prompt,
            "tools": [
                {
                    "type": "function",
                    "name": openai_realtimeapi_tool_name,
                    "description": openai_realtimeapi_tool_description,
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "request": {"type": "string", "description": openai_realtimeapi_tool_args_description}
                        },
                        "required": ["request"]
                    }
                }
            ]
        },
        "expires_after": {"anchor": "created_at", "seconds": 600}
    }


    response = await client.post(
        url=url,
        headers=headers,
        json=params
    )

    response.raise_for_status()
    result = response.json()["value"]

    return result