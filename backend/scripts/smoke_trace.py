import sys
from pathlib import Path

# Add backend directory to sys.path
backend_dir = Path(__file__).resolve().parent.parent
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

from app.config import settings
from langsmith import traceable
from langchain_openai import ChatOpenAI


@traceable(name="revenue_rescue_smoke_test")
def run_smoke_test():
    if not settings.openai_api_key:
        print("[ERROR] OPENAI_API_KEY is not set in .env!")
        sys.exit(1)

    model_name = settings.default_llm_model
    kwargs = {"model": model_name, "temperature": 0}
    if settings.openai_base_url:
        kwargs["base_url"] = settings.openai_base_url
        print(f"Using custom OpenAI Base URL: {settings.openai_base_url}")

    print(f"Initializing ChatOpenAI ({model_name})...")
    llm = ChatOpenAI(**kwargs)

    prompt = "Reply with a one-sentence confirmation that the Revenue Rescue Engine smoke test is successful."
    print(f"Sending prompt: '{prompt}'")

    response = llm.invoke(prompt)
    print("\n--- LLM Response ---")
    print(response.content)
    print("--------------------")
    print(f"\n[OK] Smoke test complete. Trace sent to LangSmith project: '{settings.langsmith_project}'")


if __name__ == "__main__":
    run_smoke_test()
