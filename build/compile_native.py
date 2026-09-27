"""Release-builder-only compiler invocation; never included as a guest tool."""
from pathlib import Path
import subprocess
import sysconfig

output=Path("/out")
output.mkdir(exist_ok=True)
subprocess.run([
    "/usr/bin/cc", "-std=c11", "-O2", "-Wall", "-Wextra", "-Werror",
    "-shared", "-fPIC", "-fvisibility=hidden", "-fstack-protector-strong",
    "-D_FORTIFY_SOURCE=3", "-Wl,-z,relro,-z,now,-z,noexecstack",
    "-I"+sysconfig.get_path("include"), "-I/source/native",
    "/source/native/confinement.c", "-o", "/out/_confinement.abi3.so",
],check=True)
