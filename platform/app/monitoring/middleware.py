from time import perf_counter


class ServerTimingMiddleware:
    """Expose application processing time separately from client/network latency."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        started = perf_counter()
        response = self.get_response(request)
        response["Server-Timing"] = f"app;dur={(perf_counter() - started) * 1000:.3f}"
        return response
