from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse

# Define custom exception
class EntityNotFoundException(HTTPException):
    def __init__(self, detail: str):
        super().__init__(status_code=404, detail=detail)

# Exception handler for EntityNotFoundException
def entity_not_found_exception_handler(request: Request, exc: EntityNotFoundException):
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": exc.detail},
    )
