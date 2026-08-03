from app.services import langfuse_tracing_service as tracing


def _reset_client_cache(monkeypatch):
    monkeypatch.setattr(tracing, "_client", None)
    monkeypatch.setattr(tracing, "_client_init_attempted", False)


def test_start_invoice_generation_is_noop_when_disabled(monkeypatch):
    _reset_client_cache(monkeypatch)
    monkeypatch.setattr(tracing.settings, "langfuse_enabled", False)

    generation = tracing.start_invoice_generation(trace_input={"a": 1}, model="gpt-5-mini")

    assert generation is None


def test_start_invoice_generation_is_noop_when_credentials_missing(monkeypatch):
    _reset_client_cache(monkeypatch)
    monkeypatch.setattr(tracing.settings, "langfuse_enabled", True)
    monkeypatch.setattr(tracing.settings, "langfuse_public_key", None)
    monkeypatch.setattr(tracing.settings, "langfuse_secret_key", None)

    generation = tracing.start_invoice_generation(trace_input={"a": 1}, model="gpt-5-mini")

    assert generation is None


def test_finish_invoice_generation_is_noop_for_none_handle():
    # Must not raise even though there's nothing to update/close.
    tracing.finish_invoice_generation(None, output={"x": 1})


def test_finish_invoice_generation_records_output_and_closes():
    class FakeGeneration:
        def __init__(self):
            self.updated_with = None
            self.ended = False

        def update(self, **kwargs):
            self.updated_with = kwargs

        def end(self):
            self.ended = True

    generation = FakeGeneration()
    tracing.finish_invoice_generation(
        generation,
        output={"ok": True},
        usage={"input": 10, "output": 5, "total": 15},
        metadata={"source_type": "image"},
    )

    assert generation.updated_with == {
        "output": {"ok": True},
        "usage_details": {"input": 10, "output": 5, "total": 15},
        "metadata": {"source_type": "image"},
    }
    assert generation.ended is True


def test_finish_invoice_generation_records_error_level():
    class FakeGeneration:
        def __init__(self):
            self.updated_with = None
            self.ended = False

        def update(self, **kwargs):
            self.updated_with = kwargs

        def end(self):
            self.ended = True

    generation = FakeGeneration()
    tracing.finish_invoice_generation(generation, error="boom")

    assert generation.updated_with == {"level": "ERROR", "status_message": "boom"}
    assert generation.ended is True


def test_finish_invoice_generation_swallows_update_errors():
    class BrokenGeneration:
        def update(self, **kwargs):
            raise RuntimeError("langfuse is down")

        def end(self):
            raise RuntimeError("still down")

    # Must not raise -- tracing failures can never break invoice parsing.
    tracing.finish_invoice_generation(BrokenGeneration(), output={"ok": True})


def test_usage_details_from_openai_response_maps_fields():
    class Usage:
        input_tokens = 100
        output_tokens = 20
        total_tokens = 120

    class Response:
        usage = Usage()

    assert tracing.usage_details_from_openai_response(Response()) == {
        "input": 100,
        "output": 20,
        "total": 120,
    }


def test_usage_details_from_openai_response_handles_missing_usage():
    class Response:
        pass

    assert tracing.usage_details_from_openai_response(Response()) is None
