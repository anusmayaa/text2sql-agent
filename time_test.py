import os
import time

from dotenv import load_dotenv
from google import genai

load_dotenv()
model = os.getenv("GEMINI_MODEL")
client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))

print("Model:", model)
start = time.time()
try:
    response = client.models.generate_content(model=model, contents="Reply with the single word: ready")
    print("Reply:", response.text)
except Exception as e:
    print("Error:", e)
print(f"Took {time.time() - start:.1f} seconds")