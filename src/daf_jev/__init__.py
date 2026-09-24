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
from daf_jev.graphical import CPT, BayesNet, Edge, Variable, decompose_single_parent
from daf_jev.graphical_elicitation import elicit_cpts, propose_structure
from daf_jev.jaggedness import (
    COIN,
    COIN_NOUL,
    D6,
    JaggednessFixture,
    chi2_sf,
    max_streak,
    noul_choice_delta,
    position_slope,
    run_battery,
    runs_test_z,
    uniform_chi2,
    uniform_deviation,
)
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

__version__ = "0.6.0"

__all__ = [
    "COIN",
    "COIN_NOUL",
    "CPT",
    "D6",
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
    "JaggednessFixture",
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
    "chi2_sf",
    "choice",
    "composite_score",
    "confidence_gate",
    "decompose_single_parent",
    "elicit_cpts",
    "get_provider",
    "list_providers",
    "load_settings",
    "max_streak",
    "noul",
    "noul_choice_delta",
    "open_async_client",
    "open_client",
    "parse_response",
    "pick_model",
    "position_slope",
    "propose_structure",
    "register_provider",
    "resolve_retry",
    "resolve_timeout",
    "route",
    "run_battery",
    "runs_test_z",
    "score",
    "uniform_chi2",
    "uniform_deviation",
]
