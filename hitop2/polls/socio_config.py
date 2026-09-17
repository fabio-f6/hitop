import json
from pathlib import Path


SOCIO_QUESTIONS = json.loads(
    Path(__file__).with_name("socio_questions.json").read_text(encoding="utf-8")
)
