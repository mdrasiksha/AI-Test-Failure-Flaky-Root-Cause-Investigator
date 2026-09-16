# Flaky Test Analyzer

This MVP provides a FastAPI service that parses uploaded JUnit XML reports into
normalized test results. It implements only project setup and JUnit parsing; it
does not attempt flaky-test detection or root-cause analysis.

## Windows setup

From a Command Prompt or PowerShell window, enter the project directory and run:

```bat
cd flaky-test-analyzer
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
pytest -v
uvicorn backend.main:app --reload
```

Open <http://127.0.0.1:8000> to see the API welcome response. Interactive
FastAPI Swagger documentation is available at <http://127.0.0.1:8000/docs>.

## Upload a report with Swagger

1. Open <http://127.0.0.1:8000/docs> after starting the server.
2. Expand **POST /upload-junit** and select **Try it out**.
3. Use **Choose File** to select `sample_data/junit.xml`.
4. Select **Execute** to view the parsed tests and status totals.

Uploaded reports are parsed in memory and are not stored.

## API endpoints

- `GET /` returns the API name.
- `GET /health` returns a basic health status.
- `POST /upload-junit` accepts one JUnit XML file as multipart form data.
