from dotenv import load_dotenv
import os

load_dotenv()

TEMPORAL_URL = os.getenv("TEMPORAL_URL")
TEMPORAL_NAMESPACE = os.getenv("TEMPORAL_NAMESPACE")
TEMPORAL_API_KEY = os.getenv("TEMPORAL_API_KEY")
