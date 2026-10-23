from translation.pipeline import TranslationRequest, translate_batch


class PublicTranslator:
    _model_key = "HachimiMT-60-QT"
    _backend = "ct2"
    last_profile = {"chunks": 2}

    def __init__(self):
        self.calls = []

    def translate_text(self, text, *, chunk_mode, beam_size):
        self.calls.append((text, chunk_mode, beam_size))
        return [], "\n".join(f"VI:{line}" for line in text.splitlines())


def test_batch_uses_public_document_api_and_restores_empty_lines():
    core = PublicTranslator()
    request = TranslationRequest(
        texts=("甲", "", "乙"), model="HachimiMT-60-QT", beam_size=2
    )
    result = translate_batch(core, request)

    assert result.texts == ("VI:甲", "", "VI:乙")
    assert core.calls == [("甲\n乙", "sentence", 2)]
    assert result.model_revision == "HachimiMT-60-QT:ct2"
    assert result.profile == {"chunks": 2}


def test_batch_rejects_layout_loss():
    class Truncated(PublicTranslator):
        def translate_text(self, text, *, chunk_mode, beam_size):
            return [], ""

    try:
        translate_batch(Truncated(), TranslationRequest(texts=("甲",), model="m"))
    except RuntimeError as exc:
        assert "đoạn nguồn" in str(exc)
    else:
        raise AssertionError("must reject output that lost a source line")
