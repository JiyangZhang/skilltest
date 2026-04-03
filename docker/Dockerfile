# SkillTest — container for running Claude Code CLI against mounted skills + run workspace.
# Build: docker build -t skilltest-claude:latest -f docker/Dockerfile docker
#
# The image does not bundle Anthropic's proprietary CLI; install `claude` in a derived image
# or mount credentials + binary at runtime. See docker/README.md.

FROM debian:bookworm-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates bash coreutils curl \
    && rm -rf /var/lib/apt/lists/*

COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

WORKDIR /workspace

ENTRYPOINT ["/entrypoint.sh"]
