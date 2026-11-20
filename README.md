# PensionPal

Answers provident fund and pension questions for workers: withdrawals, transfers, EPS pension eligibility and claim forms, citing EPFO rules and circulars.

**Status:** Day 1 foundation (FastAPI skeleton, quality gates). Live URL from Day 5.

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
