import anthropic
from .prompts import SYSTEM_PROMPT

DEFAULT_MODEL = "claude-sonnet-4-6"
MAX_TOKENS = 1024
TOKEN_WARNING_THRESHOLD = 80_000  # warn when approaching context limits


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


HISTORY_WINDOW = 24  # recent messages to keep (beyond the initial briefing pair)


class DraftConversation:
    """
    Maintains a multi-turn conversation with Claude across the entire draft.
    Keeps the initial briefing + a rolling window of recent messages so context
    stays bounded and latency doesn't grow with each round.
    """

    def __init__(self, api_key: str, model: str = DEFAULT_MODEL):
        self._client = anthropic.Anthropic(api_key=api_key)
        self.model = model
        self.messages: list[dict] = []

    def _windowed_messages(self) -> list[dict]:
        """Return briefing (first 2 msgs) + last HISTORY_WINDOW messages."""
        if len(self.messages) <= 2 + HISTORY_WINDOW:
            return self.messages
        return self.messages[:2] + self.messages[-(HISTORY_WINDOW):]

    def send(self, content: str, stream: bool = True) -> str:
        """
        Append a user message, call Claude with windowed history, append response.
        Streams by default so the user sees output as it's generated.
        """
        self.messages.append({"role": "user", "content": content})

        estimate = self.get_token_estimate()
        if estimate > TOKEN_WARNING_THRESHOLD:
            print(f"[Warning: ~{estimate:,} tokens in context, approaching limits]")

        if stream:
            response = self._stream_with_history()
        else:
            response = self._blocking_with_history()

        self.messages.append({"role": "assistant", "content": response})
        return response

    def inject_context(self, content: str) -> None:
        """
        Silently inject context (e.g. opponent picks) without making an API call.
        Pre-populates history with a user message and a canned "Noted." response
        so Claude treats it as established context on the next real send().
        """
        self.messages.append({"role": "user", "content": content})
        self.messages.append({"role": "assistant", "content": "Noted."})

    def get_token_estimate(self) -> int:
        """Rough token count: ~4 chars per token."""
        return sum(len(m["content"]) for m in self.messages) // 4

    def _stream_with_history(self) -> str:
        full_response = ""
        with self._client.messages.stream(
            model=self.model,
            max_tokens=MAX_TOKENS,
            system=SYSTEM_PROMPT,
            messages=self._windowed_messages(),
        ) as stream:
            for text in stream.text_stream:
                print(text, end="", flush=True)
                full_response += text
        print()
        return full_response

    def _blocking_with_history(self) -> str:
        msg = self._client.messages.create(
            model=self.model,
            max_tokens=MAX_TOKENS,
            system=SYSTEM_PROMPT,
            messages=self._windowed_messages(),
        )
        return msg.content[0].text
