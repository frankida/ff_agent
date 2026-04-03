import anthropic
from .prompts import SYSTEM_PROMPT

DEFAULT_MODEL = "claude-sonnet-4-6"
MAX_TOKENS = 1024


class FantasyAIClient:
    def __init__(self, api_key: str, model: str = DEFAULT_MODEL):
        self._client = anthropic.Anthropic(api_key=api_key)
        self.model = model

    def analyze(self, prompt: str, stream: bool = True) -> str:
        """
        Send a prompt to Claude and return the response.
        Streams by default so the user sees output immediately
        — important during time-sensitive draft picks.
        """
        if stream:
            return self._stream(prompt)
        return self._blocking(prompt)

    def _stream(self, prompt: str) -> str:
        full_response = ""
        with self._client.messages.stream(
            model=self.model,
            max_tokens=MAX_TOKENS,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": prompt}],
        ) as stream:
            for text in stream.text_stream:
                print(text, end="", flush=True)
                full_response += text
        print()  # trailing newline
        return full_response

    def _blocking(self, prompt: str) -> str:
        msg = self._client.messages.create(
            model=self.model,
            max_tokens=MAX_TOKENS,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": prompt}],
        )
        return msg.content[0].text

    def ping(self) -> bool:
        """Quick connectivity check — returns True if API responds."""
        try:
            msg = self._client.messages.create(
                model=self.model,
                max_tokens=10,
                messages=[{"role": "user", "content": "ping"}],
            )
            return bool(msg.content)
        except Exception:
            return False
