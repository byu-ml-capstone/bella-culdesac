"""Greeting content + logic — pulled out of main.py to demo separation of concerns.

Even a tiny app benefits from splitting content/logic from the FastAPI wiring.
As your app grows, main.py stays about the *endpoints* and their contracts;
helpers like this stay about the *data* and *rules*. See sentiment-test-app for
a bigger example: it splits into config, schemas, llm_client, local_classifier,
and device — main.py just wires them together.
"""

APP_VERSION = "0.1.1"

GREETINGS = {
    "en": "Hello, world",
    "es": "Hola, mundo",
    "fr": "Bonjour, monde",
    "de": "Hallo, Welt",
    "ja": "こんにちは、世界",
}

DEFAULT_LANG = "en"


def get_greeting(lang: str = DEFAULT_LANG) -> str:
    """Return the greeting for `lang`, or the default if unknown."""
    return GREETINGS.get(lang, GREETINGS[DEFAULT_LANG])
