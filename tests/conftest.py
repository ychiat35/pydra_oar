import shutil

import pytest

need_oar = pytest.mark.skipif(
    not (shutil.which("oarsub") and shutil.which("oarstat")),
    reason="OAR is not available",
)


try:
    import pydra.conftest as pydra_conftest

    def pytest_generate_tests(metafunc):
        return pydra_conftest.pytest_generate_tests(metafunc)

except (ImportError, AttributeError):
    pass
