Read one document from PensionPal's collection and return a small metadata record.

PensionPal covers Employees' Provident Fund (EPF), Employees' Pension Scheme (EPS), EDLI, member transfers, withdrawals, claims, and official EPFO rules, forms, FAQs, circulars, and reports.

Use only facts stated in the document. Return one JSON object matching the supplied schema, with no Markdown or explanation. Use null for a year not stated and [] for an absent list. Keep the summary to one or two plain sentences. Topics should be short subject tags. List values must be short exact names or references present in the document, not guesses.

Field meanings:
- doc_kind: the document's kind, such as rule, guideline, form, FAQ, notice, report, or reference.
- year: publication or effective year stated in the document.
- language: its main language.
- summary: what the document covers.
- topics: its main EPF, EPS, EDLI, transfer, withdrawal, or claims topics.
- schemes: scheme names explicitly covered, such as EPF Scheme, EPS, or EDLI.
- forms: EPFO form names or numbers explicitly mentioned.
- section_refs: rule, paragraph, or section references explicitly mentioned.
