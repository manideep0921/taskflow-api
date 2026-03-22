"""
Cache helpers for TaskFlow.

Keys and TTLs
─────────────
project_list:{user_id}          5 min   – project list per user
project_detail:{project_id}     10 min  – full project + members
task_list:{project_id}          5 min   – task list per project
dashboard_stats:{user_id}       2 min   – dashboard stat counts

All cache keys are namespaced so they can be invalidated precisely
without flushing the entire cache.
"""
from django.core.cache import cache
import logging

logger = logging.getLogger('taskflow.cache')

# ── TTLs (seconds) ────────────────────────────────────────────────────────────
TTL_PROJECT_LIST   = 60 * 5
TTL_PROJECT_DETAIL = 60 * 10
TTL_TASK_LIST      = 60 * 5
TTL_DASHBOARD      = 60 * 2


# ── Key builders ─────────────────────────────────────────────────────────────
def _project_list_key(user_id):
    return f'tf:project_list:{user_id}'

def _project_detail_key(project_id):
    return f'tf:project_detail:{project_id}'

def _task_list_key(project_id):
    return f'tf:task_list:{project_id}'

def _dashboard_key(user_id):
    return f'tf:dashboard:{user_id}'


# ── Getters / setters ─────────────────────────────────────────────────────────
def get_project_list(user_id):
    return cache.get(_project_list_key(user_id))

def set_project_list(user_id, data):
    cache.set(_project_list_key(user_id), data, TTL_PROJECT_LIST)

def get_project_detail(project_id):
    return cache.get(_project_detail_key(project_id))

def set_project_detail(project_id, data):
    cache.set(_project_detail_key(project_id), data, TTL_PROJECT_DETAIL)

def get_task_list(project_id):
    return cache.get(_task_list_key(project_id))

def set_task_list(project_id, data):
    cache.set(_task_list_key(project_id), data, TTL_TASK_LIST)

def get_dashboard_stats(user_id):
    return cache.get(_dashboard_key(user_id))

def set_dashboard_stats(user_id, data):
    cache.set(_dashboard_key(user_id), data, TTL_DASHBOARD)


# ── Invalidation ─────────────────────────────────────────────────────────────
def invalidate_project(project_id, member_user_ids=None):
    """Call after any project or member write."""
    keys = [_project_detail_key(project_id)]
    if member_user_ids:
        keys += [_project_list_key(uid) for uid in member_user_ids]
    cache.delete_many(keys)
    logger.debug('Cache invalidated for project %s (%d keys)', project_id, len(keys))

def invalidate_tasks(project_id):
    """Call after any task write in a project."""
    cache.delete(_task_list_key(project_id))
    logger.debug('Task cache invalidated for project %s', project_id)

def invalidate_dashboard(user_id):
    cache.delete(_dashboard_key(user_id))
