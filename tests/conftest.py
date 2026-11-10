import os
import tempfile

# Tests are hermetic: no network, no API keys, throwaway SQLite.
os.environ["LLM_ENABLED"] = "false"
os.environ["DATABASE_URL"] = "sqlite:///" + os.path.join(tempfile.mkdtemp(), "test.db").replace("\\", "/")
os.environ["GRADIO_ANALYTICS_ENABLED"] = "False"
