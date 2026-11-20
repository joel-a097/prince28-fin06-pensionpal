
# PensionPal - Requirements

## 1. Project Overview

PensionPal helps employees understand their Employees' Provident Fund (EPF) records, pension eligibility, and PF transfer process.

## 2. Target User

An employee who has changed jobs multiple times and wants to understand their EPF history and pension eligibility.

## 3. Functional Requirements

1. The API must provide a health check endpoint that returns HTTP 200 when the application is running.
2. The API must provide a readiness endpoint that returns HTTP 200 when the application is ready.
3. The API must list all available EPFO reference documents through an API endpoint.
4. The API must retrieve a document by its ID and return HTTP 404 when the ID does not exist.
5. Each EPFO reference record must contain 8 fields: id, doc_type, number, date, topic, condition, form, and effective_from.

## 4. Non-Functional Requirements

1. The API must respond to health checks within 2 seconds under normal local conditions.
2. The application must support Python 3.11 or later.
3. All API requests must include a unique request ID in the response header.
4. The application must pass at least 6 automated API tests.
5. Ruff linting and formatting checks must pass with zero reported issues.

## 5. Technology

- Python 3.11+
- FastAPI
- Pydantic
- pytest
- uv
