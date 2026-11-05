FROM python:3.12-slim@sha256:b18b261e1b4974b4f321451ad5251ded85abb22c2b8b262da527dda1d031ab30
WORKDIR /worker
COPY requirements.lock .
RUN pip install --no-cache-dir --require-hashes -r requirements.lock
COPY simulate.py .
ENV HOME=/tmp OT_API_CONFIG_DIR=/tmp/opentrons PYTHONUNBUFFERED=1
USER 10001:10001
ENTRYPOINT ["python", "/worker/simulate.py"]
