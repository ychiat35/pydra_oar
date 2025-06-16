import logging
import os
import secrets
import time
import typing as ty
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

import attrs
import pytest
from conftest import need_oar
from fileformats.generic import Directory
from pydra.compose import python, workflow
from pydra.engine.job import Job
from pydra.engine.result import Result
from pydra.engine.submitter import Submitter
from pydra.engine.tests.utils import BasicWorkflow

from pydra.workers import debug

logger = logging.getLogger("pydra.worker")


@python.define
def SleepAddOne(x):
    time.sleep(1)
    return x + 1


def test_callable_wf(any_worker, tmpdir):
    wf = BasicWorkflow(x=5)
    outputs = wf(cache_root=tmpdir)
    assert outputs.out == 9
    del wf, outputs

    # providing any_worker
    wf = BasicWorkflow(x=5)
    outputs = wf(worker="cf")
    assert outputs.out == 9
    del wf, outputs

    # providing plugin_kwargs
    wf = BasicWorkflow(x=5)
    outputs = wf(worker="cf", n_procs=2)
    assert outputs.out == 9
    del wf, outputs

    # providing wrong plugin_kwargs
    wf = BasicWorkflow(x=5)
    with pytest.raises(TypeError, match="an unexpected keyword argument"):
        wf(worker="cf", sbatch_args="-N2")

    # providing submitter
    wf = BasicWorkflow(x=5)

    with Submitter(worker=any_worker, cache_root=tmpdir) as sub:
        res = sub(wf)
    assert res.outputs.out == 9


def test_concurrent_wf(any_worker, tmpdir):
    # concurrent workflow
    # A --> C
    # B --> D
    @workflow.define(outputs=["out1", "out2"])
    def Workflow(x, y):
        taska = workflow.add(SleepAddOne(x=x), name="taska")
        taskb = workflow.add(SleepAddOne(x=y), name="taskb")
        taskc = workflow.add(SleepAddOne(x=taska.out), name="taskc")
        taskd = workflow.add(SleepAddOne(x=taskb.out), name="taskd")
        return taskc.out, taskd.out

    wf = Workflow(x=5, y=10)

    with Submitter(worker=any_worker, cache_root=tmpdir) as sub:
        results = sub(wf)

    assert not results.errored, " ".join(results.errors["error message"])
    outputs = results.outputs
    assert outputs.out1 == 7
    assert outputs.out2 == 12


def test_concurrent_wf_nprocs(tmpdir):
    # concurrent workflow
    # setting n_procs in Submitter that is passed to the worker
    # A --> C
    # B --> D
    @workflow.define(outputs=["out1", "out2"])
    def Workflow(x, y):
        taska = workflow.add(SleepAddOne(x=x), name="taska")
        taskb = workflow.add(SleepAddOne(x=y), name="taskb")
        taskc = workflow.add(SleepAddOne(x=taska.out), name="taskc")
        taskd = workflow.add(SleepAddOne(x=taskb.out), name="taskd")
        return taskc.out, taskd.out

    wf = Workflow(x=5, y=10)
    with Submitter(worker="cf", n_procs=2, cache_root=tmpdir) as sub:
        res = sub(wf)

    assert not res.errored, " ".join(res.errors["error message"])
    outputs = res.outputs
    assert outputs.out1 == 7
    assert outputs.out2 == 12


def test_wf_in_wf(any_worker, tmpdir):
    """WF(A --> SUBWF(A --> B) --> B)"""

    # workflow task
    @workflow.define
    def SubWf(x):
        sub_a = workflow.add(SleepAddOne(x=x), name="sub_a")
        sub_b = workflow.add(SleepAddOne(x=sub_a.out), name="sub_b")
        return sub_b.out

    @workflow.define
    def WfInWf(x):
        a = workflow.add(SleepAddOne(x=x), name="a")
        subwf = workflow.add(SubWf(x=a.out), name="subwf")
        b = workflow.add(SleepAddOne(x=subwf.out), name="b")
        return b.out

    wf = WfInWf(x=3)

    with Submitter(worker=any_worker, cache_root=tmpdir) as sub:
        results = sub(wf)

    assert not results.errored, " ".join(results.errors["error message"])
    outputs = results.outputs
    assert outputs.out == 7


@pytest.mark.flaky(reruns=2)  # when dask
def test_wf2(any_worker, tmpdir):
    """workflow as a node
    workflow-node with one task and no splitter
    """

    @workflow.define
    def Wfnd(x):
        add2 = workflow.add(SleepAddOne(x=x))
        return add2.out

    @workflow.define
    def Workflow(x):
        wfnd = workflow.add(Wfnd(x=x))
        return wfnd.out

    wf = Workflow(x=2)

    with Submitter(worker=any_worker, cache_root=tmpdir) as sub:
        res = sub(wf)

    assert res.outputs.out == 3


@pytest.mark.flaky(reruns=2)  # when dask
def test_wf_with_state(any_worker, tmpdir):
    @workflow.define
    def Workflow(x):
        taska = workflow.add(SleepAddOne(x=x), name="taska")
        taskb = workflow.add(SleepAddOne(x=taska.out), name="taskb")
        return taskb.out

    wf = Workflow().split(x=[1, 2, 3])

    with Submitter(cache_root=tmpdir, worker=any_worker) as sub:
        res = sub(wf)

    assert res.outputs.out[0] == 3
    assert res.outputs.out[1] == 4
    assert res.outputs.out[2] == 5


def test_debug_wf():
    # Use serial any_worker to execute workflow instead of CF
    wf = BasicWorkflow(x=5)
    outputs = wf(worker="debug")
    assert outputs.out == 9


@python.define
def Sleep(x, job_name_part):
    time.sleep(x)
    import subprocess as sp

    # getting the job_id of the first job that sleeps
    job_id = 999
    while job_id != "":
        time.sleep(3)
        id_p1 = sp.Popen(["squeue"], stdout=sp.PIPE)
        id_p2 = sp.Popen(["grep", job_name_part], stdin=id_p1.stdout, stdout=sp.PIPE)
        id_p3 = sp.Popen(["awk", "{print $1}"], stdin=id_p2.stdout, stdout=sp.PIPE)
        job_id = id_p3.communicate()[0].decode("utf-8").strip()

    return x


@python.define
def Cancel(job_name_part):
    import subprocess as sp

    # getting the job_id of the first job that sleeps
    job_id = ""
    while job_id == "":
        time.sleep(1)
        id_p1 = sp.Popen(["squeue"], stdout=sp.PIPE)
        id_p2 = sp.Popen(["grep", job_name_part], stdin=id_p1.stdout, stdout=sp.PIPE)
        id_p3 = sp.Popen(["awk", "{print $1}"], stdin=id_p2.stdout, stdout=sp.PIPE)
        job_id = id_p3.communicate()[0].decode("utf-8").strip()

    # # canceling the job
    proc = sp.run(["scancel", job_id, "--verbose"], stdout=sp.PIPE, stderr=sp.PIPE)
    # cancelling the job returns message in the sterr
    return proc.stderr.decode("utf-8").strip()


def qacct_output_to_dict(qacct_output):
    stdout_dict = {}
    for line in qacct_output.splitlines():
        key_value = line.split(None, 1)
        if key_value[0] not in stdout_dict:
            stdout_dict[key_value[0]] = []
        if len(key_value) > 1:
            stdout_dict[key_value[0]].append(key_value[1])
        else:
            stdout_dict[key_value[0]].append(None)

    print(stdout_dict)
    return stdout_dict


@need_oar
def test_oar_wf(tmpdir):
    wf = BasicWorkflow(x=1)
    # submit workflow and every task as oar job
    with Submitter(worker="oar", cache_root=tmpdir) as sub:
        res = sub(wf)

    outputs = res.outputs
    assert outputs.out == 5
    script_dir = tmpdir / "oar_scripts"
    assert script_dir.exists()
    # ensure each task was executed with oar
    assert len([sd for sd in script_dir.listdir() if sd.isdir()]) == 2


@pytest.mark.skip(
    reason=(
        "There currently isn't a way to specify a worker to run a whole workflow within "
        "a single OAR job"
    )
)
@need_oar
def test_oar_wf_cf(tmpdir):
    # submit entire workflow as single job executing with cf worker
    wf = BasicWorkflow(x=1)
    with Submitter(worker="oar", cache_root=tmpdir) as sub:
        res = sub(wf)

    outputs = res.outputs
    assert outputs.out == 5
    script_dir = tmpdir / "oar_scripts"
    assert script_dir.exists()
    # ensure only workflow was executed with oar
    sdirs = [sd for sd in script_dir.listdir() if sd.isdir()]
    assert len(sdirs) == 1
    # oar scripts should be in the dirs that are using uid in the name
    assert sdirs[0].basename == wf.uid


@need_oar
def test_oar_wf_state(tmpdir):
    wf = BasicWorkflow().split(x=[5, 6])
    with Submitter(worker="oar", cache_root=tmpdir) as sub:
        res = sub(wf)

    outputs = res.outputs
    assert outputs.out == [9, 10]
    script_dir = tmpdir / "oar_scripts"
    assert script_dir.exists()
    sdirs = [sd for sd in script_dir.listdir() if sd.isdir()]
    assert len(sdirs) == 2 * len(wf.x)


@need_oar
def test_oar_args_1(tmpdir):
    """testing sbatch_args provided to the submitter"""
    task = SleepAddOne(x=1)
    # submit workflow and every task as oar job
    with Submitter(worker="oar", cache_root=tmpdir, oarsub_args="-l nodes=2") as sub:
        res = sub(task)

    assert res.outputs.out == 2
    script_dir = tmpdir / "oar_scripts"
    assert script_dir.exists()


@need_oar
def test_oar_args_2(tmpdir):
    """testing oarsub_args provided to the submitter
    exception should be raised for invalid options
    """
    task = SleepAddOne(x=1)
    # submit workflow and every task as oar job
    with pytest.raises(RuntimeError, match="Error returned from oarsub:"):
        with Submitter(
            worker="oar", cache_root=tmpdir, oarsub_args="-l nodes=2 --invalid"
        ) as sub:
            sub(task)


def test_hash_changes_in_task_inputs_file(tmp_path):
    @python.define
    def cache_dir_as_input(out_dir: Directory) -> Directory:
        (out_dir.fspath / "new-file.txt").touch()
        return out_dir

    task = cache_dir_as_input(out_dir=tmp_path)
    with pytest.raises(RuntimeError, match="Input field hashes have changed"):
        task(cache_root=tmp_path)


def test_hash_changes_in_task_inputs_unstable(tmp_path):
    @attrs.define
    class Unstable:
        value: int  # type: ignore

        def __bytes_repr__(self, cache) -> ty.Iterator[bytes]:
            """Random 128-bit bytestring"""
            yield secrets.token_bytes(16)

    @python.define
    def unstable_input(unstable: Unstable) -> int:
        return unstable.value

    task = unstable_input(unstable=Unstable(1))
    with pytest.raises(RuntimeError, match="Input field hashes have changed"):
        task(cache_root=tmp_path)


def test_hash_changes_in_workflow_inputs(tmp_path):
    @python.define
    def OutputDirAsOutput(out_dir: Path) -> Directory:
        (out_dir / "new-file.txt").touch()
        return out_dir

    @workflow.define(outputs=["out_dir"])
    def Workflow(in_dir: Directory):
        task = workflow.add(OutputDirAsOutput(out_dir=in_dir), name="task")
        return task.out

    in_dir = tmp_path / "in_dir"
    in_dir.mkdir()
    cache_root = tmp_path / "cache_root"
    cache_root.mkdir()

    wf = Workflow(in_dir=in_dir)
    with pytest.raises(RuntimeError, match="Input field hashes have changed.*"):
        wf(cache_root=cache_root)


@python.define
def to_tuple(x, y):
    return (x, y)


class BYOAddVarWorker(debug.Worker):
    """A dummy worker that adds 1 to the output of the task"""

    _plugin_name = "byo_add_env_var"

    def __init__(self, add_var, **kwargs):
        super().__init__(**kwargs)
        self.add_var = add_var

    def run(
        self,
        task: "Job",
        rerun: bool = False,
    ) -> "Result":
        with patch.dict(os.environ, {"BYO_ADD_VAR": str(self.add_var)}):
            return super().run(task, rerun)


@python.define
def AddEnvVarTask(x: int) -> int:
    return x + int(os.environ.get("BYO_ADD_VAR", 0))


def test_byo_worker(tmp_path):

    task1 = AddEnvVarTask(x=1)

    with Submitter(worker=BYOAddVarWorker, add_var=10, cache_root=tmp_path) as sub:
        assert sub.worker.plugin_name() == "byo_add_env_var"
        result = sub(task1)

    assert result.outputs.out == 11

    task2 = AddEnvVarTask(x=2)

    new_cache_root = tmp_path / "new"

    with Submitter(worker="debug", cache_root=new_cache_root) as sub:
        result = sub(task2)

    assert result.outputs.out == 2


def test_bad_builtin_worker():

    with pytest.raises(ValueError, match="No worker matches 'bad-worker'"):
        Submitter(worker="bad-worker")


def test_bad_byo_worker1():

    import pydra.workers.base as base

    class BadWorker(base.Worker):
        def run(self, task: Job, rerun: bool = False) -> Result:
            pass

    with pytest.raises(ValueError, match="Cannot infer plugin name of Worker "):
        Submitter(worker=BadWorker)


def test_bad_byo_worker2():
    class BadWorker:
        pass

    with pytest.raises(
        TypeError,
        match="Worker must be a Worker object, name of a worker or a Worker class",
    ):
        Submitter(worker=BadWorker)
