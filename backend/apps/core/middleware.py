import time
import uuid
import logging
import threading

logger = logging.getLogger('taskflow.requests')
slow_logger = logging.getLogger('taskflow.slow_queries')

_local = threading.local()


def get_current_request_id():
    return getattr(_local, 'request_id', None)


class RequestLoggingMiddleware:
    """
    Attaches a unique X-Request-ID to every request/response,
    logs method, path, status, duration, and user.
    Flags slow requests (>500 ms) to a dedicated logger.
    """

    SLOW_THRESHOLD_MS = 500
    SKIP_PATHS = ('/static/', '/media/', '/favicon.ico')

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if any(request.path.startswith(p) for p in self.SKIP_PATHS):
            return self.get_response(request)

        request_id = request.META.get('HTTP_X_REQUEST_ID') or str(uuid.uuid4())
        _local.request_id = request_id
        request.request_id = request_id

        start = time.perf_counter()
        response = self.get_response(request)
        duration_ms = (time.perf_counter() - start) * 1000

        user = getattr(request, 'user', None)
        user_label = str(user.id) if user and user.is_authenticated else 'anon'

        log_data = {
            'request_id': request_id,
            'method': request.method,
            'path': request.path,
            'status': response.status_code,
            'duration_ms': round(duration_ms, 2),
            'user': user_label,
            'ip': self._get_ip(request),
        }

        level = logging.WARNING if response.status_code >= 500 else \
                logging.INFO    if response.status_code >= 400 else \
                logging.DEBUG

        logger.log(level, '[%(method)s] %(path)s → %(status)s in %(duration_ms).1fms (user=%(user)s req=%(request_id)s)', log_data)

        if duration_ms > self.SLOW_THRESHOLD_MS:
            slow_logger.warning(
                'SLOW REQUEST %(duration_ms).1fms [%(method)s] %(path)s (user=%(user)s req=%(request_id)s)',
                log_data
            )

        response['X-Request-ID'] = request_id
        response['X-Response-Time'] = f'{duration_ms:.1f}ms'
        _local.request_id = None
        return response

    @staticmethod
    def _get_ip(request):
        forwarded = request.META.get('HTTP_X_FORWARDED_FOR')
        if forwarded:
            return forwarded.split(',')[0].strip()
        return request.META.get('REMOTE_ADDR', '')
