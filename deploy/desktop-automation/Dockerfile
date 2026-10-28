ARG BASE_IMAGE
FROM ${BASE_IMAGE}
COPY backend/app/services/desktop_automation /app/app/services/desktop_automation
COPY backend/app/core/agent_management_scope.py /app/app/core/agent_management_scope.py
COPY backend/app/api/desktop_automation.py /app/app/api/desktop_automation.py
HEALTHCHECK --interval=15s --timeout=5s --start-period=10s CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/health', timeout=3)"
ENTRYPOINT ["uvicorn", "app.services.desktop_automation.application:app", "--host", "0.0.0.0", "--port", "8080", "--workers", "1"]
