import importlib
import os
import tempfile
import unittest


class ProviderConfigTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmpdir.cleanup)
        self.config_path = os.path.join(self.tmpdir.name, "config.json")
        os.environ["CONFIG_FILE_PATH"] = self.config_path
        import utils.config as config_module

        self.config_module = importlib.reload(config_module)

    def test_provider_defaults_to_gemini(self):
        self.assertEqual(self.config_module.get_provider_name(), "gemini")

    def test_provider_can_be_overridden(self):
        self.config_module.save_config({"provider": "openai"})
        self.assertEqual(self.config_module.get_provider_name(), "openai")


if __name__ == "__main__":
    unittest.main()
