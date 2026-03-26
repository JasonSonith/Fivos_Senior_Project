import requests


OLLAMA_URL = "http://localhost:11434/api/chat"


OLLAMA_SCHEMA = {
    "type": "object",
    "properties": {
        "brandName": {"type": ["string", "null"]},
        "versionModelNumber": {"type": ["string", "null"]},
        "catalogNumber": {"type": ["string", "null"]},
        "companyName": {"type": ["string", "null"]},
        "deviceDescription": {"type": ["string", "null"]},
    },
    "required": [
        "brandName",
        "versionModelNumber",
        "catalogNumber",
        "companyName",
        "deviceDescription",
    ],
}


def extract_gudid_fields_with_ollama(raw_gudid_text, model="llama3.2"):
    prompt = f"""
You are extracting medical device fields from GUDID content.

Return only these fields in valid JSON:
- brandName
- versionModelNumber
- catalogNumber
- companyName
- deviceDescription

If a field is not present, return null.

GUDID content:
{raw_gudid_text}
"""

    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": "Extract only the requested fields."},
            {"role": "user", "content": prompt},
        ],
        "stream": False,
        "format": OLLAMA_SCHEMA,
    }

    response = requests.post(OLLAMA_URL, json=payload, timeout=60)
    response.raise_for_status()

    data = response.json()
    content = data["message"]["content"]

    if isinstance(content, dict):
        return content

    import json
    return json.loads(content)