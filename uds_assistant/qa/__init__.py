"""Cited diagnostic Q&A ("Knowledge Pilot"): answers only from the approved layered sources.

Public API: :func:`answer_question` (see :mod:`uds_assistant.qa.answer`) and the pydantic models
in :mod:`uds_assistant.qa.models`.
"""

from uds_assistant.qa.answer import NOT_FOUND_ANSWER, answer_question
from uds_assistant.qa.confidence import qa_confidence
from uds_assistant.qa.models import AskRequest, AskResponse, QACitation

__all__ = [
    "NOT_FOUND_ANSWER",
    "AskRequest",
    "AskResponse",
    "QACitation",
    "answer_question",
    "qa_confidence",
]
