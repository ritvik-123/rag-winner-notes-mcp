FROM python:3.14-slim

WORKDIR /app

# Install dependencies first, separately from the app code -- Docker caches
# each instruction as a layer, so as long as requirements.txt doesn't change,
# rebuilding after an app code edit reuses this layer instead of
# re-downloading/reinstalling everything (torch included) every time.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# App code, notes, and the prebuilt index. Baking notes/ and index/ directly
# into the image means the container is self-contained and needs no external
# storage to answer questions -- worth remembering that this also means your
# personal notes travel with the image itself, so treat the built image with
# the same care as the notes (fine for a private registry, not something to
# push somewhere public).
COPY src/ ./src/
COPY notes/ ./notes/
COPY index/ ./index/

ENV PYTHONUNBUFFERED=1

# Stay at /app (not /app/src) so "index" and "notes" resolve the same way
# they do locally, where index/ and notes/ sit next to src/, not inside it.
# Running "python src/mcp_server.py" (script path, not a cd) still works for
# the bare "from retriever import ..." style imports inside mcp_server.py --
# Python automatically adds a script's own directory to sys.path regardless
# of the current working directory.
CMD ["python", "src/mcp_server.py"]
