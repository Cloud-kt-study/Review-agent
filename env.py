import os

from langchain_openai import ChatOpenAI

LLM_PROVIDER = os.environ.get("LLM_PROVIDER", "openai")  # openai | upstage | groq
API_KEY       = os.environ.get("API_KEY")

BASE_URLS = {
    "upstage": "https://api.upstage.ai/v1",
    "groq":    "https://api.groq.com/openai/v1",
}

DEFAULT_MODELS = {
    "openai":  "gpt-5-nano",
    "upstage": "solar-mini",
    "groq":    "llama-3.1-8b-instant",
}

llm = ChatOpenAI(
    model=os.environ.get("LLM_MODEL", DEFAULT_MODELS.get(LLM_PROVIDER, "gpt-5-nano")),
    temperature=0.2,
    api_key=API_KEY,
    base_url=BASE_URLS.get(LLM_PROVIDER),
)

DB_HOST     = os.environ.get("DB_HOST", "127.0.0.1")
DB_PORT     = int(os.environ.get("DB_PORT", "3308"))
DB_USER     = os.environ.get("DB_USER", "root")
DB_PASSWORD = os.environ.get("DB_PASSWORD", "")
DB_NAME     = os.environ.get("DB_NAME", "reviewdb")
