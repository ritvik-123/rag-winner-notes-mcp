FROM python:3.14-slim

WORKDIR /app

# Install dependencies first, separately from the app code -- Docker caches
# each instruction as a layer, so as long as requirements.txt doesn't change,
# rebuilding after an app code edit reuses this layer instead of
# re-downloading/reinstalling everything (torch included) every time.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Cache the embedding model into the image at build time, instead of letting
# every cold Cloud Run instance download it fresh from Hugging Face Hub --
# that already hit an HF rate limit once in practice, and adds latency to
# every cold start besides. HF_HOME pins where both this build-time download
# and the runtime load look for the model; HF_HUB_OFFLINE then forces every
# later lookup to use only this local cache, with zero network calls at
# runtime. This layer only depends on requirements.txt, so an app code
# change below still reuses it instead of re-downloading the model.
ENV HF_HOME=/app/.hf_cache
RUN python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('all-MiniLM-L6-v2')"
ENV HF_HUB_OFFLINE=1

# App code and the static frontend. notes/ and index/ are no longer baked in
# here -- since the multi-tenant rework, every request loads its user's
# index from GCS (vector_store.py's load_from_gcs), so a local notes/index/
# in the image would just be dead weight (and would've leaked whatever
# notes happened to be on this machine into the image).
COPY src/ ./src/
COPY frontend/ ./frontend/

ENV PYTHONUNBUFFERED=1

# Stay at /app (not /app/src) so "frontend" resolves the same way it does
# locally, where it sits next to src/, not inside it. Running
# "python src/web_api.py" (script path, not a cd) still works for the bare
# "from retriever import ..." style imports inside it -- Python automatically
# adds a script's own directory to sys.path regardless of the current
# working directory.
#
# This image is also deployed as the MCP server, by overriding this default
# at deploy time (--args src/mcp_server.py) rather than building a second
# image -- see the Deployment section in README.md.
CMD ["python", "src/web_api.py"]
