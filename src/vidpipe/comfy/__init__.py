"""ComfyUI as a backend: workflow + mapping files, an HTTP client, retries and a provider base.

ComfyUI runs as an external service; vidpipe neither installs nor manages it. To add a model, write
a workflow and its mapping file (``workflows/README.md``). To back another contract with ComfyUI,
subclass :class:`~vidpipe.comfy.provider.ComfyProvider` (see its docstring).
"""

from vidpipe.comfy.client import DEFAULT_URL as DEFAULT_URL
from vidpipe.comfy.client import ComfyClient as ComfyClient
from vidpipe.comfy.client import ComfyError as ComfyError
from vidpipe.comfy.jobs import JobOutcome as JobOutcome
from vidpipe.comfy.jobs import run_job as run_job
from vidpipe.comfy.provider import ComfyProvider as ComfyProvider
from vidpipe.comfy.workflow import WorkflowError as WorkflowError
from vidpipe.comfy.workflow import WorkflowModel as WorkflowModel
