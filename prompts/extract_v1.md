Read one document from PensionPal's collection and return a small metadata record.

PensionPal covers Employees' Provident Fund (EPF), Employees' Pension Scheme (EPS), EDLI, member transfers, withdrawals, claims, and official EPFO rules, forms, FAQs, circulars, and reports.

Use only facts stated in the document. Return one JSON object matching the supplied schema, with no Markdown or explanation. Use null for a year not stated and [] for an absent list. Keep the summary to one or two plain sentences. Topics should be short subject tags. List values must be short exact names or references present in the document, not guesses.

Field meanings:
- doc_type: the document kind, such as rule, guideline, form, FAQ, notice, report, or reference.
- number: the document, circular, or scheme number stated in the document, or null.
- date: the publication or issue date stated in the document, or null.
- topic: short EPF, EPS, EDLI, transfer, withdrawal, or claims subject tags.
- condition: eligibility or applicability conditions stated in the document.
- form: EPFO form names or numbers explicitly mentioned.
- effective_from: the date or period when the rule became effective, or null.
