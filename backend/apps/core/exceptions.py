import logging
from rest_framework.views import exception_handler
from rest_framework.response import Response
from rest_framework import status

logger = logging.getLogger(__name__)


def custom_exception_handler(exc, context):
    response = exception_handler(exc, context)

    if response is not None:
        errors = response.data
        # Normalise all error shapes to {"errors": [...]}
        if isinstance(errors, dict):
            detail_list = []
            for field, messages in errors.items():
                if isinstance(messages, list):
                    for msg in messages:
                        detail_list.append({'field': field, 'message': str(msg)})
                else:
                    detail_list.append({'field': field, 'message': str(messages)})
            response.data = {
                'errors': detail_list,
                'status_code': response.status_code,
            }
        elif isinstance(errors, list):
            response.data = {
                'errors': [{'field': 'non_field_errors', 'message': str(e)} for e in errors],
                'status_code': response.status_code,
            }
        else:
            response.data = {
                'errors': [{'field': 'detail', 'message': str(errors)}],
                'status_code': response.status_code,
            }
    else:
        logger.exception('Unhandled exception', exc_info=exc)
        response = Response(
            {
                'errors': [{'field': 'detail', 'message': 'An unexpected server error occurred.'}],
                'status_code': 500,
            },
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )

    return response
