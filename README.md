# PensionPal

[![CI](https://github.com/joel-a097/prince28-fin06-pensionpal/actions/workflows/ci.yml/badge.svg)](https://github.com/joel-a097/prince28-fin06-pensionpal/actions/workflows/ci.yml)
[![Live](https://img.shields.io/website?url=https%3A%2F%2Fpensionpal.onrender.com%2Fhealth&label=live)](https://pensionpal.onrender.com/docs)

Answers provident fund and pension questions for workers: withdrawals, transfers, EPS pension eligibility and claim forms, citing EPFO rules and circulars.

**Status:** Week 1 is deployed at https://pensionpal.onrender.com; UptimeRobot monitoring still needs account setup.

**Live:** https://pensionpal.onrender.com · [API docs](https://pensionpal.onrender.com/docs) · [health](https://pensionpal.onrender.com/health)

## Who it's for

Machine operator at an auto-parts factory in Hosur who changed jobs twice and wants to transfer PF and understand pension eligibility.

## The problem

EPF, EPS and EDLI rules are spread across schemes, circulars and FAQs. Workers may find it difficult to understand which rules apply to their situation, especially after changing jobs. Withdrawal procedures and eligibility conditions can also depend on service history and the reason for the claim.

## Data sources

EPF Scheme 1952, EPS 1995, EDLI 1976, EPFO circulars, FAQs, claim form instructions and the citizen charter.

- https://www.epfindia.gov.in/

Terms: Public EPFO documents. Cite scheme paragraph or circular number and date.

## Hardest problem (my interview story)

Rules over time and member-specific conditions: withdrawal eligibility depends on service years, reason and the latest circular, and the EPS pension estimate must be computed in code from pensionable salary and service.

## Signature feature

Claim path finder: answer 5 questions and see exactly which form to file, which documents to keep and the cited rule.

## Target metric

Correct form and rule for 90%+ of 40 member scenarios.

## Run it locally

```bash
uv sync
copy .env.example .env
```

## Run locally in one command

You need Docker Desktop running. From a fresh clone:

```bash
docker compose up --build
```

This starts Postgres (with pgvector), Redis, runs the migrations and loads the
sample data once, then starts the API.

- API docs: http://localhost:8000/docs
- Liveness: http://localhost:8000/health
- Readiness (checks the database): http://localhost:8000/ready

Stop with `Ctrl+C`, then `docker compose down`. Add `-v` to also delete the
database volume.

## Develop and test

| Task | Mac / Linux | Windows |
|---|---|---|
| Run the API with reload | `make dev` | `uv run poe dev` |
| Unit tests (no network) | `make test` | `uv run poe test` |
| Integration tests (needs `docker compose up`) | `make test-integration` | `uv run poe test-integration` |
| Coverage report | `make cov` | `uv run poe cov` |
| Lint and format check | `make lint` | `uv run poe lint` |
