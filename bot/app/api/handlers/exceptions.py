from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse
from starlette.status import HTTP_422_UNPROCESSABLE_ENTITY


# Define custom exception
class EntityNotFoundException(HTTPException):
    def __init__(self, detail: str):
        super().__init__(status_code=404, detail=detail)


class TooManyInstructionsException(HTTPException):
    def __init__(self, detail: str):
        super().__init__(status_code=400, detail=detail)


class ErrorProcessingData(HTTPException):
    def __init__(self, detail: str):
        super().__init__(status_code=502, detail=detail)


# Exception handler for EntityNotFoundException
def entity_not_found_exception_handler(request: Request, exc: HTTPException):
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": exc.detail},
    )


class BadSolanaAddressException(HTTPException):
    def __init__(self, detail: str):
        super().__init__(
            status_code=HTTP_422_UNPROCESSABLE_ENTITY,
            detail=detail
        )
