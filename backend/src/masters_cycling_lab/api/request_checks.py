from urllib.parse import urlsplit

from fastapi import Request
from fastapi.responses import JSONResponse

from masters_cycling_lab.api.errors import error_response
from masters_cycling_lab.config import Settings

UNSAFE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})


def rejected_request(request: Request, settings: Settings) -> JSONResponse | None:
    """Return an error response for requests a no-login app on 127.0.0.1 should refuse, or None.

    - Host must be one we expect. Otherwise a web page using DNS rebinding could talk to the API.
    - Browser writes must come from our own origin or an ALLOWED_ORIGINS entry. Browsers always send
      Origin on cross-site POSTs; tools like curl don't send it and are allowed.
    """
    host_header = request.headers.get("host", "")
    if urlsplit(f"//{host_header}").hostname not in settings.allowed_hosts:
        return error_response(request, 400, "HOST_NOT_ALLOWED", "This host name is not allowed.")

    origin = request.headers.get("origin")
    if request.method in UNSAFE_METHODS and origin is not None:
        own_origin = f"{request.url.scheme}://{host_header}"
        if origin != own_origin and origin not in settings.allowed_origins:
            return error_response(request, 403, "ORIGIN_NOT_ALLOWED", "Requests from this origin are not allowed.")
    return None
