import uuid

from config.logging import normalise_request_id, request_id_var


class RequestIDMiddleware:
    """Accept or generate a request id and expose it to logs and the response."""

    header_name = "X-Request-ID"

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        request_id = normalise_request_id(request.headers.get(self.header_name))
        if request_id is None:
            request_id = uuid.uuid4().hex

        request.request_id = request_id
        token = request_id_var.set(request_id)
        try:
            response = self.get_response(request)
        finally:
            request_id_var.reset(token)

        response[self.header_name] = request_id
        return response
