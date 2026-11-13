from dataclasses import dataclass


@dataclass
class ApplicationError(Exception):
    code: str
    user_message: str
    retryable: bool = False
    status_code: int = 400

    def __str__(self) -> str:
        return self.user_message

    def public_data(self) -> dict:
        return {
            "code": self.code,
            "message": self.user_message,
            "retryable": self.retryable,
        }


class InvalidSearchRequest(ApplicationError):
    def __init__(self, message: str):
        super().__init__("INVALID_REQUEST", message, False, 422)


class SearchExpired(ApplicationError):
    def __init__(self):
        super().__init__(
            "SEARCH_EXPIRED",
            "That saved search has expired. Please start the search again.",
            True,
            410,
        )


class CopartUnavailable(ApplicationError):
    def __init__(self, message: str | None = None):
        super().__init__(
            "COPART_UNAVAILABLE",
            message or "Copart could not complete the request. Please try again.",
            True,
            503,
        )


class LLMRateLimited(ApplicationError):
    def __init__(self):
        super().__init__(
            "LLM_RATE_LIMITED",
            "The assistant is temporarily busy. Please try again shortly.",
            True,
            429,
        )


class LLMUnavailable(ApplicationError):
    def __init__(self):
        super().__init__(
            "LLM_UNAVAILABLE",
            "I can’t reach the language service right now. Please try again shortly.",
            True,
            503,
        )


class OperationNotFound(ApplicationError):
    def __init__(self):
        super().__init__(
            "OPERATION_NOT_FOUND",
            "That operation could not be found.",
            False,
            404,
        )
