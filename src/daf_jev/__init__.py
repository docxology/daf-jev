"""daf-jev — a modular, composable client for the TypeSafe Jev (System One)
API.
"""

from daf_jev._errors import (
    APITimeoutError,
    APIConnectionError,
    RateLimitError,
    OverloadedError,
    TypeSafeError,
)
from daf_jev._retry import RetryPolicy
from daf_jev._types import (
    Answer,
    ChoiceAnswer,
    ChoiceQuestion,
    JSONContent,
    NoulAnswer,
    NoulQuestion,
    Question,
    ScoreAnswer,
    ScoreQuestion,
    SystemOneResponse,
    Usage,
    answer_from_wire,
    parse_response,
)
from daf_jev.client import AsyncJevClient, JevClient, ModelCard
from daf_jev.ledger import UsageLedger, UsageSnapshot
from daf_jev.resilience import CircuitBreaker, CircuitOpenError, CircuitState
from daf_jev.decider import Budget, ConfidenceGate, DecisionEvent, Decider

__version__ = "0.3.0"

# Guard: these names live in sibling modules (primitives.py, compose.py,
# config.py) built concurrently; import them best-effort so the core API
# above stays importable mid-build. The guard is permanent, not scaffolding.
try:
    from daf_jev.compose import composite_score, confidence_gate, route
    from daf_jev.primitives import QuestionSet, choice, noul, score
    from daf_jev.config import (
        Settings,
        load_settings,
        resolve_retry,
        resolve_timeout,
    )
    from daf_jev.models import pick_model
except ImportError:  # pragma: no cover - siblings not present yet
    pass

try:
    # evaluate.py is built concurrently by a sibling; import best-effort so
    # the core API above stays importable mid-build.
    from daf_jev.evaluate import EvaluationRecord, Evaluator
except ImportError:  # pragma: no cover - evaluate.py not present yet
    pass

__all__ = [
    "JevClient",
    "AsyncJevClient",
    "ModelCard",
    "NoulQuestion",
    "ChoiceQuestion",
    "ScoreQuestion",
    "Question",
    "NoulAnswer",
    "ChoiceAnswer",
    "ScoreAnswer",
    "Answer",
    "JSONContent",
    "Usage",
    "SystemOneResponse",
    "answer_from_wire",
    "parse_response",
    "RetryPolicy",
    "TypeSafeError",
    "RateLimitError",
    "OverloadedError",
    "APITimeoutError",
    "APIConnectionError",
    "noul",
    "choice",
    "score",
    "QuestionSet",
    "composite_score",
    "confidence_gate",
    "route",
    "Settings",
    "load_settings",
    "resolve_retry",
    "resolve_timeout",
    "pick_model",
    "Evaluator",
    "EvaluationRecord",
    "UsageLedger",
    "UsageSnapshot",
    "CircuitBreaker",
    "CircuitOpenError",
    "CircuitState",
    "Budget",
    "ConfidenceGate",
    "DecisionEvent",
    "Decider",
    "__version__",
]
