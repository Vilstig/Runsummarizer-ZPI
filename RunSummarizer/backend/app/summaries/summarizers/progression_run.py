from app.summaries.summarizers import easy
from app.summaries.summarizers.base import Summarizer

SUMMARIZER = Summarizer(easy.generate_params, easy.derive, easy.render)
