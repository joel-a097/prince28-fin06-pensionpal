from pensionpal.api.main import create_app
from pensionpal.core.logging_config import setup_logging

setup_logging()

app = create_app()
