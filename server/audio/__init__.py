"""Audio core: verify + transcribe + cut. Imports nothing from the web layer,
so it runs standalone from the CLI as well as inside the FastAPI service.

.env is loaded here (not only in server/config.py) so `python -m server.audio.*`
sees the same GROQ_* settings the service does. Must happen before the
submodules read os.environ at import time.
"""

from dotenv import load_dotenv

load_dotenv()
