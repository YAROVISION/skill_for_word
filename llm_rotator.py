import os
import json
import time
from openai import OpenAI
from dotenv import load_dotenv

class LLMRotator:
    def __init__(self):
        # Load from current directory
        load_dotenv()
        load_dotenv(dotenv_path='.env.local', override=True)
        
        # Fallback to search in parent directories if keys are not loaded yet
        if not any(os.getenv(k) for k in ["GROQ_API_KEY", "CEREBRAS_API_KEY", "SAMBANOVA_API_KEY", "NVIDIA_API_KEY", "CLOUDFLARE_API_KEY", "OPENROUTERFORSKILLFORDIGEST"]):
            from dotenv import find_dotenv
            env_path = find_dotenv('.env')
            if env_path:
                load_dotenv(env_path)
            env_local_path = find_dotenv('.env.local')
            if env_local_path:
                load_dotenv(env_local_path, override=True)

        self.providers = [
            {
                "name": "groq",
                "base_url": "https://api.groq.com/openai/v1",
                "api_key": os.getenv("GROQ_API_KEY"),
                "model": "llama-3.3-70b-versatile"
            },
            {
                "name": "cerebras",
                "base_url": "https://api.cerebras.ai/v1",
                "api_key": os.getenv("CEREBRAS_API_KEY"),
                "model": "llama-3.3-70b"
            },
            {
                "name": "sambanova",
                "base_url": "https://api.sambanova.ai/v1",
                "api_key": os.getenv("SAMBANOVA_API_KEY"),
                "model": "Meta-Llama-3.3-70B-Instruct"
            },
            {
                "name": "nvidia",
                "base_url": "https://integrate.api.nvidia.com/v1",
                "api_key": os.getenv("NVIDIA_API_KEY"),
                "model": "qwen/qwen3-coder-480b-a35b-instruct"
            },
            {
                "name": "nvidia_glm",
                "base_url": "https://integrate.api.nvidia.com/v1",
                "api_key": os.getenv("NVIDIA_API_KEY"),
                "model": "z-ai/glm4.7",
                "extra_body": {"chat_template_kwargs": {"enable_thinking": True, "clear_thinking": False}}
            },
            {
                "name": "cloudflare",
                "base_url": f"https://api.cloudflare.com/client/v4/accounts/{os.getenv('CLOUDFLARE_ACCOUNT_ID')}/ai/v1",
                "api_key": os.getenv("CLOUDFLARE_API_KEY"),
                "model": "@cf/meta/llama-3.1-8b-instruct"
            },
            {
                "name": "openrouter",
                "base_url": "https://openrouter.ai/api/v1",
                "api_key": os.getenv("OPENROUTERFORSKILLFORDIGEST"),
                "model": "poolside/laguna-m.1:free"
            },
            {
                "name": "ollama",
                "base_url": "http://localhost:11434/v1",
                "api_key": "ollama",
                "model": "qwen2.5-coder:14b"
            }
        ]
        
    def chat_completion(self, messages, response_format=None, preferred_provider=None):
        """
        Attempts to get a chat completion from providers in order.
        """
        # Filter out providers without API keys (except ollama)
        available_providers = [p for p in self.providers if p["api_key"] or p["name"] == "ollama"]
        
        if not available_providers:
            raise Exception("No LLM providers found.")

        # Reorder if a preferred provider is specified
        if not preferred_provider:
            preferred_provider = os.getenv("PREFERRED_PROVIDER")
        if preferred_provider:
            available_providers.sort(key=lambda x: x["name"] != preferred_provider)

        last_exception = None
        for provider in available_providers:
            try:
                print(f"🤖 [Rotator] Trying provider: {provider['name']} ({provider['model']})")
                client = OpenAI(
                    base_url=provider["base_url"],
                    api_key=provider["api_key"]
                )
                
                params = {
                    "model": provider["model"],
                    "messages": messages,
                }
                
                if response_format:
                    params["response_format"] = response_format

                if "extra_body" in provider:
                    params["extra_body"] = provider["extra_body"]

                start_time = time.time()
                response = client.chat.completions.create(**params)
                duration = time.time() - start_time
                
                content = response.choices[0].message.content
                print(f"✅ [Rotator] Success via {provider['name']} in {duration:.2f}s")
                return content

            except Exception as e:
                error_msg = str(e).lower()
                print(f"⚠️ [Rotator] Error with {provider['name']}: {e}")
                
                # Check for rate limit or specific errors that warrant a fallback
                if "rate limit" in error_msg or "429" in error_msg or "too many requests" in error_msg:
                    print(f"🔄 [Rotator] Rate limit hit for {provider['name']}. Falling back...")
                    last_exception = e
                    continue
                else:
                    last_exception = e
                    continue

        print("❌ [Rotator] All providers failed.")
        if last_exception:
            raise last_exception
        else:
            raise Exception("All LLM providers failed.")

if __name__ == "__main__":
    rotator = LLMRotator()
    try:
        res = rotator.chat_completion([{"role": "user", "content": "Say 'Hello'"}])
        print(f"Result: {res}")
    except Exception as e:
        print(f"Final Error: {e}")
