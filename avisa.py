import httpx
import json
import os
from dotenv import load_dotenv

client = httpx.AsyncClient()
load_dotenv()

avisa_token = os.getenv("AVISA_API_TOKEN")

async def send_to_whatsapp(message: str, number: int):

 url = "https://www.avisaapi.com.br/api/actions/sendMessage"


 formated_response = message.replace("**", "*")


 payload = json.dumps({
   "number": f"{number}",
   "message": f"{formated_response}"
 })

 headers = {
   "Content-Type": "application/json",
   "Authorization": f"Bearer {avisa_token}"
 }
 
 response =  await client.post(url, headers=headers, data=payload)
 response.raise_for_status()

 return response