# Image for user code containers (docs/24 §3). Pin the base digest in CI: `make sandbox-image`.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 MPLBACKEND=Agg
RUN pip install --no-cache-dir \
        numpy==2.3.3 pandas==2.3.2 scipy==1.16.2 sympy==1.14.0 matplotlib==3.10.6 \
        python-dateutil==2.9.0.post0 tabulate==0.9.0 \
    && python -c "import matplotlib.pyplot" \
    && pip uninstall -y pip setuptools wheel \
    && rm -rf /usr/local/lib/python3.12/ensurepip \
    && (find / -xdev -perm /6000 -type f -exec chmod a-s {} + 2>/dev/null; true)
ENV PIP_NO_INDEX=1

COPY run.py /opt/runner/run.py
USER 65534:65534
WORKDIR /work
ENTRYPOINT ["python", "-I", "-B", "/opt/runner/run.py"]
