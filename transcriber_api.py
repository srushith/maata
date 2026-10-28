import openai

import settings

_client = None
_client_key = None


def _get_client():
    global _client, _client_key
    api_key = settings.get(settings.API_KEY)
    if not api_key:
        raise RuntimeError("No OpenAI API key yet. Open Settings and paste your key.")
    if _client is None or api_key != _client_key:
        _client = openai.OpenAI(api_key=api_key)
        _client_key = api_key
    return _client


def _create(model, filename, options):
    with open(filename, "rb") as f:
        return _get_client().audio.transcriptions.create(model=model, file=f, **options)


def transcribe_audio(filename):
    model = settings.get(settings.MODEL) or "whisper-1"

    options = {}
    language = settings.get(settings.LANGUAGE)
    if language:
        options["language"] = language
    vocabulary = settings.get(settings.VOCABULARY)
    if vocabulary:
        # A prompt with the expected words helps the model spell them correctly.
        options["prompt"] = f"Vocabulary: {vocabulary}."

    try:
        transcript = _create(model, filename, options)
    except openai.AuthenticationError:
        raise RuntimeError("OpenAI rejected the API key. Check it in Settings.")
    except (openai.NotFoundError, openai.PermissionDeniedError):
        # The chosen model isn't available on this account; fall back to Whisper.
        if model == "whisper-1":
            raise
        transcript = _create("whisper-1", filename, options)
    return transcript.text
