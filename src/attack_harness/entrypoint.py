"""Fixed production entrypoint configuration and campaign composition."""

import os

from operator_contracts import ContractError
from operator_contracts.startup import require
from operator_contracts.validation import decode

from .composition import compose_campaign
from .contracts import load_contract
from .files import Directory
from .runtime import RuntimeStopped
from .diagnostics import close_after_failure, emit_fatal, fatal_diagnostic, report_fatal
from .startup import Startup, transport_from_environment


RELEASE_ROOT = "/opt/operator/engine"
CONTRACT_ROOT = RELEASE_ROOT + "/share/schemas"
CONFIG_NAME = "runtime-config.json"


def load_runtime_config(root=RELEASE_ROOT + "/share"):
    with Directory(root,readonly=False) as directory:
        raw=directory.read(CONFIG_NAME,64<<10)
    value=decode(raw,64<<10)
    require(type(value) is dict and set(value)=={"contract","skill_loader_digest"})
    require(type(value["contract"]) is dict and
            set(value["contract"])=={"package_version","package_digest"})
    require(type(value["skill_loader_digest"]) is str and
            value["skill_loader_digest"].startswith("sha256:") and
            len(value["skill_loader_digest"])==71)
    return value


def main():
    """Run exactly one launch; no reconnect or replacement process."""
    transport = None
    client = None
    stage = "configuration"
    try:
        config = load_runtime_config()
        stage = "contract-loading"
        protocol = load_contract(CONTRACT_ROOT, config["contract"])
        stage = "transport-startup"
        transport_name = os.environ.get("OPERATOR_TRANSPORT")
        transport = transport_from_environment(protocol)
        stage = "confinement"
        import _confinement
        stage = "bootstrap"
        session = Startup(protocol, transport, transport_name,
                          config["skill_loader_digest"], _confinement.install).run()
        client = session.client
        stage = "runtime"
        compose_campaign(protocol, session).run()
        if not client.finish_accepted:
            raise RuntimeStopped("incomplete-execution")
        return 0
    except Exception as error:
        # Accepted finish never turns a subsequent independent error into success.
        diagnostic = fatal_diagnostic(error, stage)
        report_fatal(client, diagnostic)
        if transport is not None and not close_after_failure(transport):
            diagnostic.setdefault("omissions", []).append("secondary_close_error:untrusted")
        emit_fatal(diagnostic)
        return 1
