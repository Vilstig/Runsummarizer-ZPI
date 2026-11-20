from pydantic import BaseModel, Field


class ErrorResponse(BaseModel):
    """The body of an error response."""

    detail: str = Field(description="A human-readable description of the error.")
    code: str = Field(description="A machine-readable error code.")
