# pdf-skills image.
# Self-contained — no need to build the base image separately.
#
# Build from the repo root:
#   docker build -t skilltest-pdf:latest -f skills/pdf-skills/Dockerfile .

FROM debian:bookworm-slim

# System dependencies
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ca-certificates bash coreutils curl \
        nodejs npm \
        python3 python3-pip \
    && rm -rf /var/lib/apt/lists/*

# Claude Code CLI
RUN npm install -g @anthropic-ai/claude-code

# PDF libraries required by this skill
RUN pip3 install --break-system-packages \
    pypdf \
    pdfplumber \
    reportlab

COPY docker/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

RUN mkdir -p /home/agent && chmod 1777 /home/agent
ENV HOME=/home/agent

WORKDIR /workspace

ENTRYPOINT ["/entrypoint.sh"]
