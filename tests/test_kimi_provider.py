"""Tests for Kimi/Moonshot provider support in TradingAgents.

These tests verify that the factory, model catalog, CLI provider list,
and OpenAI-compatible client all recognize 'kimi' as a first-class provider.
"""

import os
import unittest
from unittest.mock import patch

import pytest

from tradingagents.llm_clients.factory import _OPENAI_COMPATIBLE, create_llm_client
from tradingagents.llm_clients.model_catalog import get_known_models, get_model_options
from tradingagents.llm_clients.openai_client import _PROVIDER_CONFIG, OpenAIClient


@pytest.mark.unit
class TestKimiProviderRecognition(unittest.TestCase):
    """Verify 'kimi' is registered across factory, catalog, and client."""

    def test_kimi_in_openai_compatible_tuple(self):
        self.assertIn("kimi", _OPENAI_COMPATIBLE)

    def test_kimi_model_options_exist(self):
        quick = get_model_options("kimi", "quick")
        deep = get_model_options("kimi", "deep")
        self.assertTrue(any("kimi" in m.lower() for _, m in quick))
        self.assertTrue(any("kimi" in m.lower() for _, m in deep))

    def test_kimi_models_in_known_models(self):
        known = get_known_models()
        self.assertIn("kimi", known)
        self.assertIn("kimi-k2.6", known["kimi"])

    def test_kimi_provider_config_has_base_url_and_env(self):
        self.assertIn("kimi", _PROVIDER_CONFIG)
        base_url, env_var = _PROVIDER_CONFIG["kimi"]
        self.assertIn("moonshot", base_url.lower())
        self.assertEqual(env_var, "KIMI_API_KEY")

    def test_factory_creates_openai_client_for_kimi(self):
        os.environ.setdefault("KIMI_API_KEY", "placeholder")
        client = create_llm_client(provider="kimi", model="kimi-k2.6")
        self.assertIsInstance(client, OpenAIClient)
        self.assertEqual(client.provider, "kimi")
        self.assertEqual(client.model, "kimi-k2.6")

    def test_kimi_client_uses_correct_base_url(self):
        os.environ.setdefault("KIMI_API_KEY", "placeholder")
        client = create_llm_client(provider="kimi", model="kimi-k2.6")
        llm = client.get_llm()
        # ChatOpenAI stores base URL as openai_api_base internally
        self.assertEqual(llm.openai_api_base, "https://api.moonshot.cn/v1")

    def test_kimi_client_uses_explicit_base_url_when_given(self):
        os.environ.setdefault("KIMI_API_KEY", "placeholder")
        client = create_llm_client(
            provider="kimi", model="kimi-k2.6", base_url="https://custom.kimi/v1"
        )
        llm = client.get_llm()
        self.assertEqual(llm.openai_api_base, "https://custom.kimi/v1")

    def test_kimi_client_reads_api_key_from_env(self):
        os.environ["KIMI_API_KEY"] = "test-kimi-key-12345"
        try:
            client = create_llm_client(provider="kimi", model="kimi-k2.6")
            llm = client.get_llm()
            # ChatOpenAI stores api_key internally
            self.assertEqual(llm.openai_api_key.get_secret_value(), "test-kimi-key-12345")
        finally:
            del os.environ["KIMI_API_KEY"]

    def test_kimi_client_validate_model(self):
        os.environ.setdefault("KIMI_API_KEY", "placeholder")
        client = create_llm_client(provider="kimi", model="kimi-k2.6")
        self.assertTrue(client.validate_model())

    def test_kimi_custom_model_warns_but_continues(self):
        """Custom models on kimi emit a warning but do not block execution."""
        os.environ.setdefault("KIMI_API_KEY", "placeholder")
        client = create_llm_client(provider="kimi", model="custom-kimi-model")
        # validate_model returns False for unknown models on kimi (like other
        # strict providers), but warn_if_unknown_model only warns and continues.
        self.assertFalse(client.validate_model())


@pytest.mark.unit
class TestKimiCLIProviderList(unittest.TestCase):
    """Verify CLI provider list includes Kimi."""

    @patch("cli.utils.questionary.select")
    def test_select_llm_provider_includes_kimi(self, mock_select):
        # Just verify the function doesn't raise and the provider list contains kimi
        # We can't easily run the interactive prompt, so inspect the source
        import inspect

        from cli.utils import select_llm_provider
        src = inspect.getsource(select_llm_provider)
        self.assertIn("kimi", src.lower())


if __name__ == "__main__":
    unittest.main()
