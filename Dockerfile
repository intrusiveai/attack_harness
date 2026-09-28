# syntax=docker/dockerfile:1.18.0@sha256:dabfc0969b935b2080555ace70ee69a5261af8a8f1b4df97b9e7fbcf6722eddf

ARG SOURCE_DATE_EPOCH=0

FROM python@sha256:82c46c08c991d3d3ff10476ac5e386c2c28f27bbd3985a02c5e39fe99ab272eb AS builder
ARG TARGETPLATFORM
ARG SOURCE_DATE_EPOCH
ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    SOURCE_DATE_EPOCH=0
WORKDIR /source

COPY requirements-runtime.lock /source/requirements-runtime.lock
RUN python3 -m pip download --require-hashes --only-binary=:all: \
      --dest /wheelhouse -r /source/requirements-runtime.lock
RUN python3 -m pip install --no-index --no-deps --no-compile --require-hashes \
      --find-links /wheelhouse --target /release/opt/operator/engine/lib \
      -r /source/requirements-runtime.lock

COPY bootstrap.py /source/bootstrap.py
COPY src/attack_harness /source/src/attack_harness
COPY assets/default-system-prompt.txt /source/assets/default-system-prompt.txt
COPY native/confinement.c native/live_allowlist.h /source/native/
COPY build/compile_native.py build/prepare_release.py build/contract-lock.json /source/build/
COPY build/context/contracts /source/contracts

RUN --network=none PYTHONPATH=/release/opt/operator/engine/lib:/source/src:/source/contracts/source/contracts/python \
    python3 /source/build/prepare_release.py \
      --source-root /source --contract-package /source/contracts \
      --contract-lock /source/build/contract-lock.json --output /release \
      --platform "$TARGETPLATFORM" --prompt /source/assets/default-system-prompt.txt
RUN --network=none python3 /source/build/compile_native.py
RUN install -m 0444 /out/_confinement.abi3.so \
      /release/opt/operator/engine/lib/_confinement.abi3.so

FROM builder AS test
ENV PYTHONPATH=/release/opt/operator/engine/lib:/source \
    OPERATOR_CONTRACT_SOURCE=/source/contracts/source/schemas
COPY tests /source/tests
RUN --network=none python3 -m unittest discover -s /source/tests -v
RUN --network=none python3 /source/build/prepare_release.py --verify \
      --contract-package /source/contracts \
      --contract-lock /source/build/contract-lock.json --output /release

FROM gcr.io/distroless/python3-debian13@sha256:8ee214843129f43e2ebf5e0ca9f2e4e6d8292143d1b8a6787f169b5898578884 AS runtime
ARG SOURCE_DATE_EPOCH
COPY --from=test --chown=0:0 /release /
USER 65532:65532
WORKDIR /run/operator/work
ENTRYPOINT ["/usr/bin/python3", "-I", "-S", "-B", "/opt/operator/engine/bootstrap.py"]
