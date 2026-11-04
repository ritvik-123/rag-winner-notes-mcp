FROM python:3.14-slim

WORKDIR /app

# Install dependencies first, separately from the app code -- Docker caches
# each instruction as a layer, so as long as requirements.txt doesn't change,
# rebuilding after an app code edit reuses this layer instead of
# re-downloading/reinstalling everything (torch included) every time.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

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
