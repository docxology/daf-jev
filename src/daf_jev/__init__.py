"""daf-jev — a modular, composable client for the TypeSafe Jev (System One)
API.
"""

from daf_jev._errors import (
    APIConnectionError,
    APITimeoutError,
    OverloadedError,
    RateLimitError,
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
from daf_jev.client import (
    AsyncJevClient,
    JevClient,
    ModelCard,
    open_async_client,
    open_client,
)
from daf_jev.compose import composite_score, confidence_gate, route
from daf_jev.config import (
    Settings,
    load_settings,
    resolve_retry,
    resolve_timeout,
)
from daf_jev.decider import Budget, ConfidenceGate, Decider, DecisionEvent
from daf_jev.evaluate import EvaluationRecord, Evaluator
from daf_jev.graphical import CPT, BayesNet, Edge, Variable
from daf_jev.graphical_elicitation import elicit_cpts, propose_structure
from daf_jev.ledger import UsageLedger, UsageSnapshot
from daf_jev.models import pick_model
from daf_jev.primitives import QuestionSet, choice, noul, score
from daf_jev.providers import (
    ProviderSpec,
    get_provider,
    list_providers,
    register_provider,
)
from daf_jev.resilience import CircuitBreaker, CircuitOpenError, CircuitState

__version__ = "0.5.0"

__all__ = [
    "CPT",
    "APIConnectionError",
    "APITimeoutError",
    "Answer",
    "AsyncJevClient",
    "BayesNet",
    "Budget",
    "ChoiceAnswer",
    "ChoiceQuestion",
    "CircuitBreaker",
    "CircuitOpenError",
    "CircuitState",
    "ConfidenceGate",
    "Decider",
    "DecisionEvent",
    "Edge",
    "EvaluationRecord",
    "Evaluator",
    "JSONContent",
    "JevClient",
    "ModelCard",
    "NoulAnswer",
    "NoulQuestion",
    "OverloadedError",
    "ProviderSpec",
    "Question",
    "QuestionSet",
    "RateLimitError",
    "RetryPolicy",
    "ScoreAnswer",
    "ScoreQuestion",
    "Settings",
    "SystemOneResponse",
    "TypeSafeError",
    "Usage",
    "UsageLedger",
    "UsageSnapshot",
    "Variable",
    "__version__",
    "answer_from_wire",
    "choice",
    "composite_score",
    "confidence_gate",
    "elicit_cpts",
    "get_provider",
    "list_providers",
    "load_settings",
    "noul",
    "open_async_client",
    "open_client",
    "parse_response",
    "pick_model",
    "propose_structure",
    "register_provider",
    "resolve_retry",
    "resolve_timeout",
    "route",
    "score",
]
