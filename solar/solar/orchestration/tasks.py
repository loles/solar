
from functools import partial, wraps
from itertools import islice
import subprocess
import time

from celery.app import task
from celery import group
from celery.exceptions import Ignore
import redis

from solar.orchestration import graph
from solar.core import actions
from solar.core import resource
from solar.system_log.tasks import commit_logitem, error_logitem
from solar.orchestration.runner import app
from solar.orchestration.traversal import traversal


r = redis.StrictRedis(host='10.0.0.2', port=6379, db=1)


__all__ = ['solar_resource', 'cmd', 'sleep',
           'error', 'fault_tolerance', 'schedule_start', 'schedule_next']

# NOTE(dshulyak) i am not using celery.signals because it is not possible
# to extrace task_id from *task_success* signal
class ReportTask(task.Task):

    def on_success(self, retval, task_id, args, kwargs):
        schedule_next.apply_async(args=[task_id, 'SUCCESS'], queue='scheduler')
        commit_logitem.apply_async(args=[task_id], queue='system_log')

    def on_failure(self, exc, task_id, args, kwargs, einfo):
        schedule_next.apply_async(
            args=[task_id, 'ERROR'],
            kwargs={'errmsg': str(einfo.exception)},
            queue='scheduler')
        error_logitem.apply_async(args=[task_id], queue='system_log')


report_task = partial(app.task, base=ReportTask, bind=True)


@report_task
def solar_resource(ctxt, resource_name, action):
    res = resource.load(resource_name)
    return actions.resource_action(res, action)


@report_task
def cmd(ctxt, cmd):
    popen = subprocess.Popen(
        cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, shell=True)
    out, err = popen.communicate()
    rcode = popen.returncode
    if rcode:
        raise Exception('Command %s failed with err %s', cmd, err)
    return popen.returncode, out, err


@report_task
def sleep(ctxt, seconds):
    time.sleep(seconds)


@report_task
def error(ctxt, message):
    raise Exception('message')


@report_task
def fault_tolerance(ctxt, percent):
    task_id = ctxt.request.id
    plan_uid, task_name = task_id.rsplit(':', 1)

    dg = graph.get_graph(plan_uid)
    success = 0.0
    predecessors = dg.predecessors(task_name)
    lth = len(predecessors)

    for s in predecessors:
        if dg.node[s]['status'] == 'SUCCESS':
            success += 1

    succes_percent = (success/lth) * 100
    if succes_percent < percent:
        raise Exception('Cant proceed with, {0} < {1}'.format(
            succes_percent, percent))


@report_task
def echo(ctxt, message):
    return message


@report_task
def anchor(ctxt, *args):
    # such tasks should be walked when atleast 1/3/exact number of resources visited
    dg = graph.get_graph('current')
    for s in dg.predecessors(ctxt.request.id):
        if dg.node[s]['status'] != 'SUCCESS':
            raise Exception('One of the tasks erred, cant proceeed')


def schedule(plan_uid, dg):
    next_tasks = list(traverse(dg, control_tasks=(fault_tolerance,)))
    graph.save_graph(plan_uid, dg)
    group(next_tasks)()


@app.task
def schedule_start(plan_uid, start=None, end=None):
    """On receive finished task should update storage with task result:

    - find successors that should be executed
    - apply different policies to tasks
    """
    dg = graph.get_graph(plan_uid)
    schedule(plan_uid, dg)


@app.task
def soft_stop(plan_uid):
    dg = graph.get_graph(plan_uid)
    for n in dg:
        if dg.node[n]['status'] == 'PENDING':
            dg.node[n]['status'] = 'SKIPPED'
    graph.save_graph(plan_uid, dg)


@app.task
def schedule_next(task_id, status, errmsg=None):
    plan_uid, task_name = task_id.rsplit(':', 1)
    dg = graph.get_graph(plan_uid)
    dg.node[task_name]['status'] = status
    dg.node[task_name]['errmsg'] = errmsg

    schedule(plan_uid, dg)
