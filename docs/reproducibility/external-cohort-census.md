# External cohort census

Input-only census of the curated CSV at source revision `3a44e398d9fed3f08cf396f1153be2960193f581`, SHA-256 `247473787c33fb22ee48a4177593188f2a2c6ef140756566fe4610fee89ba333`. Aryl/amine SMILES were canonicalized with the locked RDKit version. No outcomes were supplied to an acquisition policy.

| Source | Raw rows | Canonical substrate pairs | Pairs with at least 48 raw rows | Pairs shared with Doyle |
| --- | ---: | ---: | ---: | ---: |
| AZ ELN 2023 | 750 | 469 | 0 | 0 |
| Dreher 2014 | 768 | 8 | 8 | 0 |
| Dreher 2016 | 144 | 18 | 0 | 0 |
| Dreher Doyle 2018 | 4312 | 15 | 15 | 15 |
| HiTEA 2024 | 2632 | 27 | 13 | 0 |
| JNJ HTE 2024 | 11328 | 888 | 12 | 0 |
| Merck 2025 | 4204 | 4204 | 0 | 0 |
| Roche 2023 | 3359 | 123 | 18 | 0 |

These are raw-row counts, not qualified campaign counts. Repeated rows, missing measurements, condition identities, record-level provenance, and rights for each original source still require verification. No source above has been newly registered, trained on, or included in the expanded result table. The Doyle portion overlaps the existing reference and must not be counted as independent evidence.

The source provides catalyst/solvent fields and derived product features rather than the complete role contract used by reference v1. A future normalization version must preserve full experimental conditions, including additive identity; product/outcome-derived columns remain excluded from model inputs. Cross-source canonical reaction identity must be checked beyond shared substrate pairs.

Source context: [pinned repository README](https://github.com/schwallergroup/bh-hte-ood/blob/3a44e398d9fed3f08cf396f1153be2960193f581/README.md). The locally retained audit is `artifacts/external-cohort-census.json`. This census identifies candidates for source-independent follow-up; it does not establish original-record licensing or benchmark eligibility.
