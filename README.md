# What is pydra_oar?

`pydra_oar` is an [OAR](https://oar.imag.fr/) plugin for [Pydra](https://github.com/nipype/pydra), based on the [pydra-workers-template](https://github.com/nipype/pydra-workers-template).

Pydra is a lightweight dataflow engine for Python 3.11+. It was originally developed by the neuroimaging community but is applicable to any scientific domain that requires a flexible task execution engine.

Workflows can be executed locally using `concurrent.futures` or distributed on HPC/Cloud resources through resource managers such as Slurm, SGE, Dask, and OAR.


# How to install pydra_oar?

## Developer mode

We recommend installing the Python dependencies in a virtual environment. On [Grid5000](https://www.grid5000.fr/w/Grid5000:Home), the default Python version is 3.9, so you should explicitly use a Python 3.11+ virtual environment.

```bash
path_of_python3.11 -m venv venv_pydra_oar_python3.11
source venv_pydra_oar_python3.11/bin/activate

cd ~
git clone https://github.com/nipype/pydra.git
cd pydra
pip install -e .[dev]

cd ~
git clone https://github.com/ychiat35/pydra_oar.git
cd pydra_oar
pip install -e .[dev]
```

## TODO: Installation from PyPI

# How to use the pydra_oar plugin?
With `pydra` and `pydra_oar` installed, you can run the following basic example:

```python
from pydra.engine import Submitter
from pydra.compose import python, workflow
import os

@python.define
def add_two(x):
    return x + 2

wf_cache_dir = os.path.join(os.getcwd(), 'cache-wf')

@workflow.define(outputs=["out"])
def Workflow(x):
    wf = workflow.add(add_two(x=x))
    return wf.out

wf1 = Workflow(x=3)
with Submitter(worker="oar", cache_root=wf_cache_dir, oarsub_args="-l host=1/core=1") as sub:
    res = sub(wf1)

print(res.outputs)
```

You should see something like: `WorkflowOutputs(out=5)`.


**NOTE**: To avoid unnecessary recomputation, Pydra uses a cache directory. By default, it stores cache data under `/tmp`, which is **not shared across frontend and compute nodes on Grid5000**.
For distributed computations, make sure to set `cache_root` to a path available both locally and on compute nodes (e.g., via NFS or a shared volume).


# How to run the tests
You can run the plugin’s tests using `pytest`:

```bash
cd pydra_oar
pytest tests --basetemp=$HOME/tmpdir_pydra_oar
```
**NOTE**: For the same reason explained in the [How to use the pydra_oar plugin? section](#how-to-use-the-pydra_oar-plugin), we recommend using a directory under `$HOME` for `--basetemp` on Grid5000, to ensure the temporary directory is accessible from both frontend and compute nodes.


# TODO: How to release pydra_oar

Create a tag matching the version to release in gitlab, it should create a pipeline which will push the package to PyPi.
When a tag is pushed, the package should be uploaded to PyPI with a valid API token placed in the respository secrets.

The setuptools_scm tool allows for versioning based on the most recent git tag. The release process can thus be:

```
git tag -a 1.0.0
python -m build
twine upload dist/*
```
Note that uploading to PyPI is done via Continuous integration when a tag is pushed to the repository, so only the first step needs to be donne manually.

Note also that we assume tags will be version numbers and not be prefixed with v or some other string. See setuptools_scm documentation for alternative configurations.