"""Tests for Kimi Coding Plan provider support in TradingAgents."""

import os
import unittest

import pytest

from tradingagents.llm_clients.factory import _OPENAI_COMPATIBLE, create_llm_client
from tradingagents.llm_clients.model_catalog import get_known_models, get_model_options


@pytest.mark.unit
class TestKimiCodingProvider(unittest.TestCase):
    """Verify Kimi Coding Plan is a first-class Anthropic Messages provider."""

    def test_kimi_coding_is_not_openai_compatible(self):
        self.assertNotIn("kimi-coding", _OPENAI_COMPATIBLE)

    def test_kimi_coding_model_options_exist(self):
        quick = get_model_options("kimi-coding", "quick")
        deep = get_model_options("kimi-coding", "deep")
        self.assertIn(("Kimi K2.6 Coding Plan", "kimi-k2.6"), quick)
        self.assertIn(("Kimi for Coding", "kimi-for-coding"), deep)

    def test_kimi_coding_models_in_known_models(self):
        known = get_known_models()
        self.assertIn("kimi-coding", known)
        self.assertIn("kimi-k2.6", known["kimi-coding"])
        self.assertIn("kimi-for-coding", known["kimi-coding"])

    def test_factory_creates_kimi_coding_client(self):
        os.environ.setdefault("KIMI_API_KEY", "placeholder")
        client = create_llm_client(provider="kimi-coding", model="kimi-k2.6")
        self.assertEqual(client.provider, "kimi-coding")
        self.assertEqual(client.model, "kimi-k2.6")
        self.assertEqual(client.base_url, None)
        self.assertTrue(client.validate_model())

    def test_kimi_coding_llm_uses_coding_endpoint_headers_and_key(self):
        os.environ["KIMI_API_KEY"] = "test-kimi-coding-key-12345"
        try:
            client = create_llm_client(provider="kimi-coding", model="kimi-k2.6")
            llm = client.get_llm()
            self.assertEqual(str(llm.model), "kimi-k2.6")
            self.assertEqual(str(llm.anthropic_api_url), "https://api.kimi.com/coding")
            self.assertEqual(
                llm.anthropic_api_key.get_secret_value(),
                "test-kimi-coding-key-12345",
            )
            self.assertEqual(llm.default_headers["User-Agent"], "claude-code/0.1.0")
        finally:
            del os.environ["KIMI_API_KEY"]

    def test_kimi_coding_llm_allows_explicit_base_url(self):
        os.environ.setdefault("KIMI_API_KEY", "placeholder")
        client = create_llm_client(
            provider="kimi-coding",
            model="kimi-for-coding",
            base_url="https://proxy.example.com/coding",
        )
        llm = client.get_llm()
        self.assertEqual(str(llm.anthropic_api_url), "https://proxy.example.com/coding")


if __name__ == "__main__":
    unittest.main()
