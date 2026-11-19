
# PensionPal - Requirements

## 1. Project Overview

PensionPal helps employees understand their Employees' Provident Fund (EPF) records, pension eligibility, and PF transfer process.

## 2. Target User

An employee who has changed jobs multiple times and wants to understand their EPF history and pension eligibility.

## 3. Core Requirements

- Provide information about EPF documents.
- Store structured EPFO reference records.
- Allow users to retrieve document information.
- Explain relevant eligibility conditions.
- Provide a health check endpoint.
- Provide a readiness check endpoint.

## 4. Technology

- Python 3.11+
- FastAPI
- Pydantic
- pytest
- uv

## 5. Data Fields

Each EPFO reference record must contain:

- id
- doc_type
- number
- date
- topic
- condition
- form
- effective_from
